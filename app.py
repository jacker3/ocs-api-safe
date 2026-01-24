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

# Отключаем предупреждения о небезопасных запросах
urllib3.disable_warnings(InsecureRequestWarning)

# Настройка логирования без фильтра на этом этапе
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Отключаем логи urllib3 для уменьшения шума
logging.getLogger('urllib3').setLevel(logging.WARNING)

load_dotenv()

app = Flask(__name__)
CORS(app)

# Кастомный фильтр для логирования с IP
class IPLogFilter(logging.Filter):
    def filter(self, record):
        # Проверяем, есть ли контекст приложения
        try:
            from flask import has_app_context
            if has_app_context() and hasattr(g, 'client_ip'):
                record.client_ip = g.client_ip
            else:
                record.client_ip = 'system'
        except RuntimeError:
            record.client_ip = 'system'
        return True

# Middleware для логирования IP
@app.before_request
def log_request_info():
    # Получаем реальный IP клиента (учитываем прокси)
    if request.headers.get('X-Forwarded-For'):
        client_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        client_ip = request.headers.get('X-Real-IP')
    else:
        client_ip = request.remote_addr
    
    # Сохраняем IP в g для использования в логах
    g.client_ip = client_ip
    
    # Логируем входящий запрос
    logger.info(f"Запрос {request.method} {request.path} от {client_ip}")

# Глобальная переменная для IP сервера
SERVER_IP = None

def get_server_ip():
    """Получает внешний IP сервера"""
    global SERVER_IP
    if SERVER_IP:
        return SERVER_IP
    
    try:
        # Пробуем получить IP через проверенные сервисы
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
                    logger.info(f"Внешний IP сервера: {SERVER_IP} (получен с {service})")
                    return SERVER_IP
            except Exception as e:
                logger.debug(f"Не удалось получить IP с {service}: {e}")
                continue
        
        # Если не удалось получить IP, используем локальный
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            local_ip = s.getsockname()[0]
            s.close()
            SERVER_IP = local_ip
            logger.info(f"Локальный IP сервера: {SERVER_IP}")
        except:
            SERVER_IP = 'unknown'
            
        return SERVER_IP
    except Exception as e:
        logger.error(f"Ошибка получения IP сервера: {e}")
        SERVER_IP = 'unknown'
        return SERVER_IP

def test_ocs_connection():
    """Тестирует соединение с OCS API разными способами"""
    results = []
    api_key = os.getenv('OCS_API_KEY')
    
    if not api_key:
        return {"status": "no_api_key", "message": "API ключ не настроен"}
    
    # Тест 1: DNS разрешение
    try:
        start = time.time()
        ocs_ip = socket.gethostbyname('connector.b2b.ocs.ru')
        dns_time = time.time() - start
        results.append({
            "test": "dns",
            "status": "success",
            "ip": ocs_ip,
            "time_ms": round(dns_time * 1000, 2)
        })
    except Exception as e:
        results.append({
            "test": "dns",
            "status": "failed",
            "error": str(e)
        })
    
    # Тест 2: TCP соединение (порт 443)
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('connector.b2b.ocs.ru', 443))
        sock.close()
        tcp_time = time.time() - start
        results.append({
            "test": "tcp_443",
            "status": "success",
            "time_ms": round(tcp_time * 1000, 2)
        })
    except Exception as e:
        results.append({
            "test": "tcp_443",
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
                'User-Agent': 'Connection-Test/1.0'
            },
            timeout=10,
            params={'limit': 1},
            verify=False  # Отключаем проверку SSL для теста
        )
        http_time = time.time() - start
        
        results.append({
            "test": "http_api",
            "status": "success" if response.status_code == 200 else "failed",
            "status_code": response.status_code,
            "time_ms": round(http_time * 1000, 2),
            "headers": dict(response.headers)
        })
    except requests.exceptions.Timeout as e:
        results.append({
            "test": "http_api",
            "status": "timeout",
            "error": "Таймаут 10 секунд"
        })
    except Exception as e:
        results.append({
            "test": "http_api",
            "status": "failed",
            "error": str(e)
        })
    
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "server_ip": get_server_ip(),
        "tests": results,
        "summary": {
            "all_success": all(r.get('status') in ['success'] for r in results),
            "has_timeout": any(r.get('status') == 'timeout' for r in results),
            "has_connection": any(r.get('test') == 'tcp_443' and r.get('status') == 'success' for r in results)
        }
    }

class OCSAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://connector.b2b.ocs.ru/api/v2"
        
        # Получаем IP сервера
        self.server_ip = get_server_ip()
        logger.info(f"OCSAPI инициализирован. Сервер IP: {self.server_ip}")
        
        # Тестируем соединение при инициализации
        self.connection_test = test_ocs_connection()
        logger.info(f"Результат теста соединения: {self.connection_test['summary']}")
        
        # Создаем сессию
        self.session = requests.Session()
        
        # Настраиваем User-Agent
        self.user_agent = f"OCS-Proxy/1.0 (Server: {self.server_ip})"
        
        # Настраиваем адаптер с ретраями
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=3,
            pool_maxsize=3,
            max_retries=1,  # Уменьшаем ретраи для Render
            pool_block=False
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        
        # Устанавливаем заголовки
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': self.user_agent,
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'close',  # Используем close вместо keep-alive
        })
        
        # Таймауты (уменьшаем для Render)
        self.timeout = (3, 8)  # 3 секунды на соединение, 8 на чтение
    
    def _make_request(self, endpoint: str, params=None):
        try:
            url = f"{self.base_url}/{endpoint}"
            
            # Добавляем timestamp для отслеживания
            request_id = datetime.datetime.now().strftime('%H%M%S%f')[-6:]
            logger.info(f"[{request_id}] Запрос к OCS: {endpoint}")
            
            # Делаем запрос
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
                    data = response.json()
                    logger.debug(f"[{request_id}] Успешно, {len(str(data))} символов")
                    return data
                except json.JSONDecodeError as e:
                    logger.error(f"[{request_id}] Ошибка JSON: {e}")
                    return None
            else:
                logger.warning(f"[{request_id}] Ошибка {response.status_code}")
                if response.status_code in [403, 429]:
                    logger.error(f"[{request_id}] Возможная блокировка OCS (статус {response.status_code})")
                return None
                
        except requests.exceptions.Timeout as e:
            logger.error(f"Таймаут запроса к OCS API: {e}")
            return {"_error": "timeout", "message": "Превышено время ожидания (8с)"}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ошибка соединения с OCS API: {e}")
            return {"_error": "connection", "message": "Ошибка соединения"}
        except Exception as e:
            logger.error(f"Ошибка OCS API: {type(e).__name__}: {e}")
            return None
    
    def get_categories(self):
        logger.info("Запрос категорий")
        return self._make_request("catalog/categories")
    
    def get_shipment_cities(self):
        logger.info("Запрос городов")
        return self._make_request("logistic/shipment/cities")
    
    def get_products_by_category(self, categories: str, shipment_city: str, **params):
        endpoint = f"catalog/categories/{categories}/products"
        base_params = {
            'shipmentcity': shipment_city,
            'limit': params.get('limit', 20),  # Уменьшаем для скорости
        }
        
        if 'search' in params:
            base_params['search'] = params['search']
        
        logger.info(f"Товары по категории: {categories}")
        return self._make_request(endpoint, params=base_params)
    
    def search_products(self, search_term: str, shipment_city: str, **params):
        endpoint = "catalog/categories/all/products"
        base_params = {
            'shipmentcity': shipment_city,
            'search': search_term,
            'limit': params.get('limit', 20)
        }
        
        logger.info(f"Поиск: {search_term}")
        return self._make_request(endpoint, params=base_params)

# Инициализация API
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
    logger.info(f"API ключ найден (длина: {len(api_key)})")
    ocs_api = OCSAPI(api_key=api_key)
    # Запускаем тест соединения
    connection_info = test_ocs_connection()
    logger.info(f"Соединение с OCS: {connection_info['summary']}")
else:
    logger.warning("API ключ не найден, демо-режим")
    ocs_api = None

# Получаем IP сервера один раз при запуске
server_ip = get_server_ip()
logger.info(f"Сервер запущен. IP: {server_ip}")

# Кэш
cache = {}
CACHE_TTL = 600  # 10 минут для Render

# Настройка CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    
    # Добавляем информацию о сервере
    response.headers.add('X-Server-IP', server_ip)
    response.headers.add('X-Server-Location', 'Render.com' if os.environ.get('RENDER') else 'Local')
    response.headers.add('X-OCS-Status', 'active' if ocs_api and ocs_api.connection_test['summary']['has_connection'] else 'inactive')
    
    # Логируем исходящий ответ
    logger.info(f"Ответ {response.status_code} для {request.path}")
    
    return response

@app.route('/')
def home():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    # Получаем информацию о соединении
    connection_status = "unknown"
    if ocs_api:
        connection_status = "connected" if ocs_api.connection_test['summary']['has_connection'] else "disconnected"
    
    return jsonify({
        "status": "success", 
        "message": "OCS API Proxy для Render.com",
        "environment": "Render.com" if os.environ.get('RENDER') else "Development",
        "server": {
            "ip": server_ip,
            "hostname": socket.gethostname(),
            "location": "Render.com" if os.environ.get('RENDER') else "Local",
            "ocs_connection": connection_status
        },
        "client": {
            "ip": client_ip,
            "user_agent": request.headers.get('User-Agent')
        },
        "api": {
            "configured": bool(ocs_api),
            "status": connection_status,
            "timeout_seconds": 8
        },
        "timestamp": datetime.datetime.now().isoformat(),
        "endpoints": {
            "health": "/api/health",
            "diagnostics": "/api/diagnostics",
            "categories": "/api/categories",
            "connection_test": "/api/connection-test"
        }
    })

@app.route('/api/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "server_ip": server_ip,
        "timestamp": datetime.datetime.now().isoformat(),
        "ocs_api_available": bool(ocs_api and ocs_api.connection_test['summary']['has_connection'])
    })

@app.route('/api/diagnostics')
def diagnostics():
    """Полная диагностика системы"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    # Информация о Render
    render_info = {
        "service": os.environ.get('RENDER_SERVICE_NAME'),
        "instance": os.environ.get('RENDER_INSTANCE_ID'),
        "region": os.environ.get('RENDER_REGION'),
        "is_render": bool(os.environ.get('RENDER'))
    }
    
    # Тест соединения с OCS
    connection_test = test_ocs_connection() if api_key else {"status": "no_api_key"}
    
    return jsonify({
        "server": {
            "ip": server_ip,
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            "working_directory": os.getcwd(),
            "environment_variables": {
                "RENDER": bool(os.environ.get('RENDER')),
                "PORT": os.environ.get('PORT', '10000')
            }
        },
        "render": render_info,
        "client": {
            "ip": client_ip,
            "headers": {
                "user_agent": request.headers.get('User-Agent'),
                "x_forwarded_for": request.headers.get('X-Forwarded-For'),
                "x_real_ip": request.headers.get('X-Real-IP')
            }
        },
        "ocs_api": {
            "configured": bool(api_key),
            "key_length": len(api_key) if api_key else 0,
            "domain": "connector.b2b.ocs.ru",
            "connection_test": connection_test
        },
        "diagnosis": {
            "likely_issue": "OCS API блокирует IP Render" if connection_test.get('summary', {}).get('has_connection') and not connection_test.get('summary', {}).get('all_success') else "unknown",
            "recommendation": "Связаться с поддержкой OCS для разблокировки IP" if connection_test.get('summary', {}).get('has_timeout') else "Проверить API ключ и сетевые настройки"
        },
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/connection-test')
def connection_test():
    """Тест соединения с OCS API"""
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
        "tests": test_results['tests'],
        "summary": test_results['summary'],
        "timestamp": test_results['timestamp'],
        "conclusion": "OCS API доступен с этого сервера" if test_results['summary']['all_success'] else 
                     "OCS API недоступен. Возможна блокировка IP адреса." if test_results['summary']['has_connection'] else
                     "Проблемы с сетью или DNS."
    })

@app.route('/api/categories')
def get_categories():
    """Получение категорий"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    cache_key = 'categories'
    
    # Проверяем кэш
    if cache_key in cache:
        cache_time, data = cache[cache_key]
        if (datetime.datetime.now() - cache_time).seconds < CACHE_TTL:
            logger.info("Возвращаем категории из кэша")
            return jsonify({
                "success": True,
                "data": data,
                "cached": True,
                "source": "cache",
                "client_ip": client_ip,
                "server_ip": server_ip
            })
    
    if not ocs_api:
        # Демо-данные
        demo_data = {
            "result": [
                {"id": "1", "name": "Компьютеры и ноутбуки (демо)"},
                {"id": "2", "name": "Комплектующие для ПК (демо)"},
                {"id": "3", "name": "Периферия (демо)"},
                {"id": "4", "name": "Сети и серверы (демо)"},
                {"id": "5", "name": "Оргтехника (демо)"}
            ],
            "_demo": True
        }
        return jsonify({
            "success": True,
            "data": demo_data,
            "cached": False,
            "source": "demo",
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    
    logger.info(f"Запрос категорий от {client_ip}")
    categories = ocs_api.get_categories()
    
    # Логируем результат
    if categories and not categories.get('_error'):
        cache[cache_key] = (datetime.datetime.now(), categories)
        logger.info(f"Успешно получено {len(categories.get('result', []))} категорий")
        return jsonify({
            "success": True,
            "data": categories,
            "cached": False,
            "source": "ocs_api",
            "client_ip": client_ip,
            "server_ip": server_ip,
            "ocs_status": "online"
        })
    else:
        logger.warning(f"Ошибка при получении категорий: {categories.get('_error') if categories else 'timeout'}")
        # Возвращаем демо-данные при ошибке
        demo_data = {
            "result": [
                {"id": "1", "name": "Компьютеры (демо, ошибка OCS)"},
                {"id": "2", "name": "Комплектующие (демо, ошибка OCS)"}
            ],
            "_demo": True,
            "_error": categories.get('_error') if categories else "timeout"
        }
        return jsonify({
            "success": False,
            "data": demo_data,
            "error": categories.get('message') if categories else "OCS API недоступен",
            "client_ip": client_ip,
            "server_ip": server_ip,
            "ocs_status": "offline",
            "debug": {
                "server_ip": server_ip,
                "likely_issue": "OCS блокирует IP Render.com"
            }
        })

# Остальные эндпоинты (cities, products/category, products/search) остаются похожими
# с использованием безопасного подхода как в get_categories()

@app.route('/api/cities')
def get_cities():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    cache_key = 'cities'
    
    if cache_key in cache:
        cache_time, data = cache[cache_key]
        if (datetime.datetime.now() - cache_time).seconds < CACHE_TTL:
            return jsonify({
                "success": True,
                "data": data,
                "cached": True,
                "client_ip": client_ip,
                "server_ip": server_ip
            })
    
    if not ocs_api:
        demo_data = ["Красноярск (демо)", "Москва (демо)", "Новосибирск (демо)"]
        return jsonify({
            "success": True,
            "data": demo_data,
            "cached": False,
            "source": "demo",
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    
    cities = ocs_api.get_shipment_cities()
    
    if cities and not cities.get('_error'):
        cache[cache_key] = (datetime.datetime.now(), cities)
        return jsonify({
            "success": True,
            "data": cities,
            "cached": False,
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    else:
        default_cities = ["Красноярск", "Москва"]
        return jsonify({
            "success": True,
            "data": default_cities,
            "cached": False,
            "api_error": cities.get('_error') if cities else "timeout",
            "client_ip": client_ip,
            "server_ip": server_ip,
            "source": "fallback"
        })

@app.errorhandler(Exception)
def handle_exception(e):
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    logger.error(f"Необработанное исключение: {type(e).__name__}: {e}")
    
    return jsonify({
        "success": False,
        "error": str(e),
        "type": type(e).__name__,
        "client_ip": client_ip,
        "server_ip": server_ip,
        "timestamp": datetime.datetime.now().isoformat(),
        "note": "Это ошибка прокси-сервера, не OCS API"
    }), 500

if __name__ == '__main__':
    # Добавляем фильтр IP
    logger.addFilter(IPLogFilter())
    
    port = int(os.environ.get('PORT', 10000))
    
    logger.info(f"Запуск OCS Proxy на порту {port}")
    logger.info(f"Сервер IP: {server_ip}")
    logger.info(f"Render окружение: {'Да' if os.environ.get('RENDER') else 'Нет'}")
    logger.info(f"API ключ: {'Настроен' if api_key else 'Не настроен'}")
    
    # Запускаем начальный тест соединения
    if api_key:
        initial_test = test_ocs_connection()
        logger.info(f"Начальный тест OCS: {initial_test['summary']}")
        if not initial_test['summary']['all_success']:
            logger.warning(f"OCS API может быть недоступен с IP {server_ip}")
            logger.warning("Рекомендация: связаться с поддержкой OCS для разблокировки IP Render")
    
    app.run(host='0.0.0.0', port=port, debug=False)