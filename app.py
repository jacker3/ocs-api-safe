import os
import requests
import logging
import json
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from dotenv import load_dotenv
import sys
import datetime
import socket
import time
import urllib3
from urllib3.exceptions import InsecureRequestWarning
from functools import wraps
from typing import Union, Dict, List, Any

# Отключаем предупреждения о небезопасных запросах
urllib3.disable_warnings(InsecureRequestWarning)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Отключаем логи urllib3
logging.getLogger('urllib3').setLevel(logging.WARNING)

load_dotenv()

app = Flask(__name__)
CORS(app)

# Кастомный фильтр для логирования с IP
class IPLogFilter(logging.Filter):
    def filter(self, record):
        try:
            from flask import has_app_context
            if has_app_context() and hasattr(g, 'client_ip'):
                record.client_ip = g.client_ip
            else:
                record.client_ip = 'system'
        except RuntimeError:
            record.client_ip = 'system'
        return True

# Добавляем фильтр
logger.addFilter(IPLogFilter())

# Middleware для логирования IP
@app.before_request
def log_request_info():
    # Получаем реальный IP клиента
    if request.headers.get('X-Forwarded-For'):
        client_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        client_ip = request.headers.get('X-Real-IP')
    else:
        client_ip = request.remote_addr
    
    g.client_ip = client_ip
    
    logger.info(f"Запрос {request.method} {request.path} от {client_ip}")

# Вспомогательная функция для безопасного доступа к данным
def safe_get(data: Union[Dict, List], key: str, default: Any = None) -> Any:
    """Безопасно получает значение из данных, которые могут быть dict или list"""
    if isinstance(data, dict):
        return data.get(key, default)
    return default

# Глобальные переменные
SERVER_IP = None
OCS_BLOCKED = False

def get_server_ip() -> str:
    """Получает внешний IP сервера"""
    global SERVER_IP
    if SERVER_IP:
        return SERVER_IP
    
    try:
        services = [
            'https://api.ipify.org',
            'https://ident.me',
            'https://checkip.amazonaws.com'
        ]
        
        for service in services:
            try:
                response = requests.get(service, timeout=3)
                if response.status_code == 200:
                    SERVER_IP = response.text.strip()
                    logger.info(f"Внешний IP сервера: {SERVER_IP}")
                    return SERVER_IP
            except:
                continue
        
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            SERVER_IP = s.getsockname()[0]
            s.close()
            logger.info(f"Локальный IP сервера: {SERVER_IP}")
        except:
            SERVER_IP = 'unknown'
            
        return SERVER_IP
    except Exception as e:
        logger.error(f"Ошибка получения IP сервера: {e}")
        SERVER_IP = 'unknown'
        return SERVER_IP

def test_ocs_connection() -> Dict:
    """Тестирует соединение с OCS API"""
    results = []
    api_key = os.getenv('OCS_API_KEY')
    
    if not api_key:
        return {
            "status": "no_api_key", 
            "message": "API ключ не настроен",
            "tests": [],
            "summary": {"all_success": False, "has_timeout": False, "has_connection": False}
        }
    
    # Тест 1: DNS
    try:
        start = time.time()
        ocs_ip = socket.gethostbyname('connector.b2b.ocs.ru')
        dns_time = time.time() - start
        results.append({
            "test": "dns_resolution",
            "status": "success",
            "ip": ocs_ip,
            "time_ms": round(dns_time * 1000, 2)
        })
    except Exception as e:
        results.append({
            "test": "dns_resolution",
            "status": "failed",
            "error": str(e)
        })
    
    # Тест 2: TCP порт 443
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('connector.b2b.ocs.ru', 443))
        sock.close()
        tcp_time = time.time() - start
        results.append({
            "test": "tcp_connection_443",
            "status": "success",
            "time_ms": round(tcp_time * 1000, 2)
        })
    except Exception as e:
        results.append({
            "test": "tcp_connection_443",
            "status": "failed",
            "error": str(e)
        })
    
    # Тест 3: Быстрый HTTP запрос
    try:
        start = time.time()
        response = requests.get(
            "https://connector.b2b.ocs.ru/api/v2/catalog/categories",
            headers={
                'accept': 'application/json',
                'X-API-Key': api_key,
                'User-Agent': 'OCS-Connection-Test/1.0'
            },
            timeout=7,
            params={'limit': 1},
            verify=False
        )
        http_time = time.time() - start
        
        results.append({
            "test": "http_api_request",
            "status": "success" if response.status_code == 200 else "failed",
            "status_code": response.status_code,
            "time_ms": round(http_time * 1000, 2),
            "response_size": len(response.text)
        })
    except requests.exceptions.Timeout:
        results.append({
            "test": "http_api_request",
            "status": "timeout",
            "error": "Таймаут 7 секунд"
        })
    except Exception as e:
        results.append({
            "test": "http_api_request",
            "status": "failed",
            "error": str(e)
        })
    
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "server_ip": get_server_ip(),
        "tests": results,
        "summary": {
            "all_success": all(r.get('status') == 'success' for r in results),
            "has_timeout": any(r.get('status') == 'timeout' for r in results),
            "has_connection": any(r.get('test') == 'tcp_connection_443' and r.get('status') == 'success' for r in results)
        }
    }

class OCSAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://connector.b2b.ocs.ru/api/v2"
        
        self.server_ip = get_server_ip()
        logger.info(f"OCSAPI инициализирован. Сервер IP: {self.server_ip}")
        
        # Тест соединения
        self.connection_test = test_ocs_connection()
        test_summary = self.connection_test['summary']
        
        global OCS_BLOCKED
        OCS_BLOCKED = test_summary['has_timeout'] or not test_summary['has_connection']
        
        if OCS_BLOCKED:
            logger.warning(f"OCS API вероятно блокирует IP {self.server_ip}")
            logger.warning("Используем демо-режим. Свяжитесь с поддержкой OCS для разблокировки.")
        else:
            logger.info(f"Соединение с OCS API: OK")
        
        # Создаем сессию только если не блокирован
        if not OCS_BLOCKED:
            self.session = requests.Session()
            
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=2,
                pool_maxsize=2,
                max_retries=0,
                pool_block=False
            )
            self.session.mount('https://', adapter)
            
            self.session.headers.update({
                'accept': 'application/json',
                'X-API-Key': self.api_key,
                'User-Agent': f'OCS-Render-Proxy/1.0 (IP:{self.server_ip})',
                'Accept-Encoding': 'gzip',
                'Connection': 'close'
            })
            
            self.timeout = (3, 6)
        else:
            self.session = None
            logger.info("Режим: Демо-данные (OCS заблокирован)")
    
    def _make_request(self, endpoint: str, params=None) -> Dict:
        """Выполняет запрос к OCS API или возвращает демо-данные"""
        # Если OCS заблокирован, сразу возвращаем демо-данные
        global OCS_BLOCKED
        if OCS_BLOCKED or not self.session:
            return self._get_demo_data(endpoint, params)
        
        try:
            url = f"{self.base_url}/{endpoint}"
            request_id = datetime.datetime.now().strftime('%H%M%S%f')[-6:]
            
            logger.info(f"[{request_id}] Запрос: {endpoint}")
            
            start_time = time.time()
            response = self.session.get(
                url, 
                params=params, 
                timeout=self.timeout,
                verify=True
            )
            request_duration = time.time() - start_time
            
            logger.info(f"[{request_id}] Ответ: {response.status_code} за {request_duration:.2f}с")
            
            if response.status_code == 200:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    logger.error(f"[{request_id}] Ошибка парсинга JSON")
                    return self._get_demo_data(endpoint, params)
            else:
                if response.status_code in [403, 429]:
                    OCS_BLOCKED = True
                    logger.error(f"[{request_id}] OCS заблокировал запрос (статус {response.status_code})")
                return self._get_demo_data(endpoint, params)
                
        except requests.exceptions.Timeout:
            OCS_BLOCKED = True
            logger.error("Таймаут OCS API. Активируем демо-режим.")
            return self._get_demo_data(endpoint, params)
        except Exception as e:
            logger.error(f"Ошибка OCS API: {e}")
            return self._get_demo_data(endpoint, params)
    
    def _get_demo_data(self, endpoint: str, params=None) -> Dict:
        """Возвращает демо-данные для разных эндпоинтов в формате словаря"""
        global OCS_BLOCKED
        demo_data = {
            "_demo": True,
            "_ocs_blocked": OCS_BLOCKED,
            "_server_ip": self.server_ip,
            "_timestamp": datetime.datetime.now().isoformat()
        }
        
        if 'categories' in endpoint:
            demo_data["result"] = [
                {"id": "1", "name": "Компьютеры и ноутбуки (демо)"},
                {"id": "2", "name": "Комплектующие для ПК (демо)"},
                {"id": "3", "name": "Периферия (демо)"},
                {"id": "4", "name": "Сети и серверы (демо)"},
                {"id": "5", "name": "Оргтехника (демо)"}
            ]
        elif 'cities' in endpoint:
            # Для городов возвращаем словарь с результатом в списке
            demo_data["result"] = ["Красноярск (демо)", "Москва (демо)", "Новосибирск (демо)"]
        elif 'products' in endpoint:
            category = safe_get(params, 'category', 'all') if params else 'all'
            search = safe_get(params, 'search', '') if params else ''
            
            if search:
                product_name = f"Результат поиска: {search} (демо)"
            else:
                product_name = f"Товар категории {category} (демо)"
            
            demo_data["result"] = [
                {
                    "id": "1",
                    "name": product_name,
                    "price": 45000,
                    "category": category if category != 'all' else "Компьютеры",
                    "brand": "Demo Brand",
                    "availability": True
                },
                {
                    "id": "2", 
                    "name": "Дополнительный товар (демо)",
                    "price": 1500,
                    "category": "Периферия",
                    "brand": "Demo Brand",
                    "availability": True
                }
            ]
        else:
            demo_data["result"] = []
        
        return demo_data
    
    def get_categories(self) -> Dict:
        return self._make_request("catalog/categories")
    
    def get_shipment_cities(self) -> Dict:
        """Всегда возвращаем словарь, даже для городов"""
        result = self._make_request("logistic/shipment/cities")
        
        # Если результат - список (старый формат), преобразуем в словарь
        if isinstance(result, list):
            return {
                "result": result,
                "_converted": True,
                "_demo": True,
                "_ocs_blocked": True
            }
        
        return result
    
    def get_products_by_category(self, categories: str, shipment_city: str, **params) -> Dict:
        endpoint = f"catalog/categories/{categories}/products"
        base_params = {'shipmentcity': shipment_city, 'limit': params.get('limit', 20)}
        if 'search' in params:
            base_params['search'] = params['search']
        return self._make_request(endpoint, params=base_params)
    
    def search_products(self, search_term: str, shipment_city: str, **params) -> Dict:
        endpoint = "catalog/categories/all/products"
        base_params = {
            'shipmentcity': shipment_city,
            'search': search_term,
            'limit': params.get('limit', 20)
        }
        return self._make_request(endpoint, params=base_params)

# Инициализация
api_key = os.getenv('OCS_API_KEY')
if not api_key:
    logger.warning("OCS_API_KEY не найден!")
    possible_keys = ['API_KEY', 'OCS_API', 'OCS_KEY']
    for key in possible_keys:
        if os.getenv(key):
            api_key = os.getenv(key)
            logger.info(f"Найден ключ в переменной {key}")
            break

if api_key:
    logger.info(f"API ключ найден")
    ocs_api = OCSAPI(api_key=api_key)
    # Тест соединения
    connection_info = test_ocs_connection()
    logger.info(f"Тест соединения: {'OK' if connection_info['summary']['all_success'] else 'FAILED'}")
else:
    logger.warning("API ключ не найден, только демо-режим")
    ocs_api = None

server_ip = get_server_ip()
logger.info(f"Сервер IP: {server_ip}")
logger.info(f"Render окружение: {'Да' if os.environ.get('RENDER') else 'Нет'}")

# Кэш
cache = {}
CACHE_TTL = 300

# Настройка CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    
    response.headers.add('X-Server-IP', server_ip)
    response.headers.add('X-Server-Location', 'Render.com' if os.environ.get('RENDER') else 'Local')
    response.headers.add('X-OCS-Status', 'blocked' if OCS_BLOCKED else 'active')
    
    logger.info(f"Ответ {response.status_code} для {request.path}")
    
    return response

# Главная страница
@app.route('/')
def home():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    return jsonify({
        "status": "success", 
        "message": "OCS API Proxy для Render.com",
        "environment": "Render.com" if os.environ.get('RENDER') else "Development",
        "server": {
            "ip": server_ip,
            "ocs_status": "blocked" if OCS_BLOCKED else "active",
            "api_configured": bool(api_key)
        },
        "client": {
            "ip": client_ip
        },
        "note": "Если OCS блокирует IP Render, используются демо-данные",
        "endpoints": {
            "api_categories": "/api/categories",
            "api_cities": "/api/cities", 
            "api_products": "/api/products/category?category=all&shipment_city=Красноярск",
            "diagnostics": "/api/diagnostics",
            "connection_test": "/api/connection-test"
        },
        "timestamp": datetime.datetime.now().isoformat()
    })

# API эндпоинты
@app.route('/api/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "server_ip": server_ip,
        "ocs_blocked": OCS_BLOCKED,
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/diagnostics')
def diagnostics():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    connection_test = test_ocs_connection() if api_key else {"status": "no_api_key"}
    
    return jsonify({
        "server": {
            "ip": server_ip,
            "hostname": socket.gethostname(),
            "platform": sys.platform,
            "render": bool(os.environ.get('RENDER'))
        },
        "client": {
            "ip": client_ip,
            "user_agent": request.headers.get('User-Agent')
        },
        "ocs_api": {
            "configured": bool(api_key),
            "blocked": OCS_BLOCKED,
            "connection_test": connection_test
        },
        "diagnosis": {
            "issue": "OCS API блокирует IP Render.com" if OCS_BLOCKED else "Нет проблем",
            "recommendation": "Свяжитесь с поддержкой OCS и предоставьте IP: " + server_ip if OCS_BLOCKED else "Все работает"
        },
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/connection-test')
def connection_test():
    if not api_key:
        return jsonify({
            "success": False,
            "error": "API ключ не настроен",
            "timestamp": datetime.datetime.now().isoformat()
        })
    
    test_results = test_ocs_connection()
    
    return jsonify({
        "success": test_results['summary']['all_success'],
        "server_ip": server_ip,
        "blocked": OCS_BLOCKED,
        "tests": test_results['tests'],
        "summary": test_results['summary'],
        "timestamp": test_results['timestamp'],
        "action_required": OCS_BLOCKED,
        "action_message": "Свяжитесь с поддержкой OCS для разблокировки IP: " + server_ip if OCS_BLOCKED else ""
    })

@app.route('/api/categories')
def get_categories():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    cache_key = f'categories_{client_ip}'
    
    # Проверяем кэш
    if cache_key in cache:
        cache_time, data = cache[cache_key]
        if (datetime.datetime.now() - cache_time).seconds < CACHE_TTL:
            logger.info("Категории из кэша")
            return jsonify({
                "success": True,
                "data": data,
                "cached": True,
                "source": "cache",
                "client_ip": client_ip,
                "server_ip": server_ip,
                "ocs_blocked": safe_get(data, '_ocs_blocked', OCS_BLOCKED)
            })
    
    if not ocs_api:
        # Демо-данные если API не настроен
        demo_data = {
            "result": [
                {"id": "1", "name": "Компьютеры (API не настроен)"},
                {"id": "2", "name": "Комплектующие (API не настроен)"}
            ],
            "_demo": True,
            "_api_configured": False
        }
        return jsonify({
            "success": True,
            "data": demo_data,
            "cached": False,
            "source": "demo_no_api",
            "client_ip": client_ip,
            "server_ip": server_ip,
            "ocs_blocked": True
        })
    
    logger.info(f"Запрос категорий от {client_ip}")
    categories = ocs_api.get_categories()
    
    # Всегда проверяем, что categories - это словарь
    if not isinstance(categories, dict):
        categories = {
            "result": categories if isinstance(categories, list) else [],
            "_converted": True,
            "_demo": True
        }
    
    # Сохраняем в кэш
    if categories:
        cache[cache_key] = (datetime.datetime.now(), categories)
    
    return jsonify({
        "success": True,
        "data": categories,
        "cached": False,
        "source": "ocs_api" if not safe_get(categories, '_demo') else "demo_blocked",
        "client_ip": client_ip,
        "server_ip": server_ip,
        "ocs_blocked": safe_get(categories, '_ocs_blocked', OCS_BLOCKED),
        "note": "Используются демо-данные, т.к. OCS блокирует IP Render" if safe_get(categories, '_demo') else ""
    })

@app.route('/api/cities')
def get_cities():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    cache_key = f'cities_{client_ip}'
    
    if cache_key in cache:
        cache_time, data = cache[cache_key]
        if (datetime.datetime.now() - cache_time).seconds < CACHE_TTL:
            return jsonify({
                "success": True,
                "data": data,
                "cached": True,
                "client_ip": client_ip,
                "ocs_blocked": safe_get(data, '_ocs_blocked', OCS_BLOCKED)
            })
    
    if not ocs_api:
        demo_data = {
            "result": ["Красноярск", "Москва", "Новосибирск"],
            "_demo": True
        }
        return jsonify({
            "success": True,
            "data": demo_data,
            "cached": False,
            "source": "demo",
            "client_ip": client_ip,
            "ocs_blocked": True
        })
    
    cities = ocs_api.get_shipment_cities()
    
    # Гарантируем, что cities - это словарь
    if not isinstance(cities, dict):
        cities = {
            "result": cities if isinstance(cities, list) else [],
            "_converted": True,
            "_demo": True,
            "_ocs_blocked": OCS_BLOCKED
        }
    
    if cities:
        cache[cache_key] = (datetime.datetime.now(), cities)
    
    return jsonify({
        "success": True,
        "data": cities,
        "cached": False,
        "source": "ocs_api" if not safe_get(cities, '_demo') else "demo",
        "client_ip": client_ip,
        "ocs_blocked": safe_get(cities, '_ocs_blocked', OCS_BLOCKED)
    })

@app.route('/api/products/category')
def get_products_by_category():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 20, type=int)
    
    logger.info(f"Товары: категория={category}, город={shipment_city}")
    
    if not ocs_api:
        demo_data = {
            "result": [
                {
                    "id": "1",
                    "name": f"Товар 1 (демо, категория: {category})",
                    "price": 1000,
                    "category": category
                }
            ],
            "_demo": True
        }
        return jsonify({
            "success": True,
            "data": demo_data,
            "source": "demo",
            "client_ip": client_ip,
            "ocs_blocked": True
        })
    
    products = ocs_api.get_products_by_category(
        categories=category,
        shipment_city=shipment_city,
        limit=limit
    )
    
    # Гарантируем, что products - это словарь
    if not isinstance(products, dict):
        products = {
            "result": products if isinstance(products, list) else [],
            "_converted": True,
            "_demo": True,
            "_ocs_blocked": OCS_BLOCKED
        }
    
    return jsonify({
        "success": True,
        "data": products,
        "source": "ocs_api" if not safe_get(products, '_demo') else "demo",
        "client_ip": client_ip,
        "ocs_blocked": safe_get(products, '_ocs_blocked', OCS_BLOCKED),
        "request": {
            "category": category,
            "shipment_city": shipment_city,
            "limit": limit
        }
    })

@app.route('/api/products/search')
def search_products():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 20, type=int)
    
    if not search_term:
        return jsonify({"success": False, "error": "Не указан поисковый запрос"}), 400
    
    if not ocs_api:
        demo_data = {
            "result": [
                {
                    "id": "1",
                    "name": f"Результат поиска: {search_term} (демо)",
                    "price": 1000,
                    "category": "Разное"
                }
            ],
            "_demo": True
        }
        return jsonify({
            "success": True,
            "data": demo_data,
            "source": "demo",
            "client_ip": client_ip,
            "ocs_blocked": True
        })
    
    products = ocs_api.search_products(
        search_term=search_term,
        shipment_city=shipment_city,
        limit=limit
    )
    
    # Гарантируем, что products - это словарь
    if not isinstance(products, dict):
        products = {
            "result": products if isinstance(products, list) else [],
            "_converted": True,
            "_demo": True,
            "_ocs_blocked": OCS_BLOCKED
        }
    
    return jsonify({
        "success": True,
        "data": products,
        "search_term": search_term,
        "source": "ocs_api" if not safe_get(products, '_demo') else "demo",
        "client_ip": client_ip,
        "ocs_blocked": safe_get(products, '_ocs_blocked', OCS_BLOCKED)
    })

# Обработчик 404
@app.errorhandler(404)
def not_found_error(error):
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    path = request.path
    
    logger.info(f"404: {path} от {client_ip}")
    
    return jsonify({
        "success": False,
        "error": "Страница не найдена",
        "path": path,
        "available_endpoints": [
            "/",
            "/api/health",
            "/api/diagnostics",
            "/api/connection-test",
            "/api/categories",
            "/api/cities",
            "/api/products/category",
            "/api/products/search"
        ]
    }), 404

@app.errorhandler(Exception)
def handle_exception(e):
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    logger.error(f"Ошибка: {type(e).__name__}: {e}", exc_info=True)
    
    return jsonify({
        "success": False,
        "error": str(e),
        "type": type(e).__name__,
        "client_ip": client_ip,
        "server_ip": server_ip,
        "timestamp": datetime.datetime.now().isoformat(),
        "note": "Это ошибка прокси-сервера"
    }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    logger.info("=" * 60)
    logger.info(f"Запуск OCS Proxy на порту {port}")
    logger.info(f"Сервер IP: {server_ip}")
    logger.info(f"OCS API статус: {'ЗАБЛОКИРОВАН' if OCS_BLOCKED else 'ДОСТУПЕН'}")
    logger.info(f"API ключ: {'Настроен' if api_key else 'Не настроен'}")
    logger.info("=" * 60)
    
    if OCS_BLOCKED and api_key:
        logger.warning("ВАЖНО: OCS API блокирует запросы с IP Render.com")
        logger.warning(f"Предоставьте этот IP поддержке OCS: {server_ip}")
        logger.warning("Пока используются демо-данные")
    
    app.run(host='0.0.0.0', port=port, debug=False)