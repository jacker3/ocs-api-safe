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

# Кастомный фильтр для логирования с IP - будет добавлен позже
class IPLogFilter(logging.Filter):
    def filter(self, record):
        # Проверяем, есть ли контекст приложения
        try:
            from flask import has_app_context, g
            if has_app_context() and hasattr(g, 'client_ip'):
                record.client_ip = g.client_ip
            else:
                record.client_ip = 'system'
        except RuntimeError:
            record.client_ip = 'system'
        return True

# Пока не добавляем фильтр, добавим позже в контексте приложения
# logger.addFilter(IPLogFilter())

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

# Функция для безопасного логирования с IP
def safe_log_info(message, **kwargs):
    """Безопасное логирование с проверкой контекста"""
    try:
        from flask import has_app_context, g
        if has_app_context() and hasattr(g, 'client_ip'):
            ip_info = f" [IP: {g.client_ip}]"
        else:
            ip_info = " [IP: system]"
    except RuntimeError:
        ip_info = " [IP: system]"
    
    logger.info(f"{message}{ip_info}", **kwargs)

def get_server_ip():
    """Получает внешний IP сервера"""
    try:
        # Пробуем получить IP через проверенные сервисы
        services = [
            'https://api.ipify.org',
            'https://ident.me',
            'https://checkip.amazonaws.com'
        ]
        
        for service in services:
            try:
                response = requests.get(service, timeout=2)
                if response.status_code == 200:
                    ip = response.text.strip()
                    safe_log_info(f"Внешний IP сервера: {ip} (получен с {service})")
                    return ip
            except:
                continue
        
        # Если не удалось получить IP, используем локальный
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
        safe_log_info(f"Локальный IP сервера: {local_ip}")
        return local_ip
    except Exception as e:
        logger.error(f"Ошибка получения IP сервера: {e}")
        return 'unknown'

def get_ip_info(ip_address):
    """Получает базовую информацию об IP"""
    try:
        # Простая проверка типа IP
        if ip_address == '127.0.0.1' or ip_address.startswith('192.168.') or ip_address.startswith('10.'):
            return {
                'type': 'private',
                'location': 'local_network'
            }
        
        # Для публичных IP можно использовать простой API (опционально)
        try:
            response = requests.get(f'http://ip-api.com/json/{ip_address}', timeout=3)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    return {
                        'type': 'public',
                        'country': data.get('country'),
                        'city': data.get('city'),
                        'isp': data.get('isp'),
                        'org': data.get('org')
                    }
        except:
            pass
        
        return {
            'type': 'public',
            'location': 'unknown'
        }
    except Exception as e:
        logger.debug(f"Не удалось получить информацию об IP {ip_address}: {e}")
        return None

class OCSAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://connector.b2b.ocs.ru/api/v2"
        
        # Получаем IP сервера для логирования
        self.server_ip = get_server_ip()
        safe_log_info(f"OCSAPI инициализирован. Сервер IP: {self.server_ip}")
        
        # Создаем сессию с оптимизированными настройками
        self.session = requests.Session()
        
        # Добавляем User-Agent с информацией о сервере
        self.user_agent = f"OCS-Proxy/1.0 (Server-IP: {self.server_ip})"
        
        # Настраиваем пул соединений
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=5,
            pool_maxsize=10,
            max_retries=2,
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
            'Connection': 'keep-alive'
        })
        
        # Таймауты
        self.timeout = (5, 15)  # 5 секунд на соединение, 15 на чтение
    
    def _make_request(self, endpoint: str, params=None, client_ip=None):
        try:
            url = f"{self.base_url}/{endpoint}"
            
            # Логируем информацию о запросе
            safe_log_info(f"Запрос к OCS API: {endpoint}")
            
            # Добавляем информацию о клиенте в User-Agent
            headers = self.session.headers.copy()
            if client_ip and client_ip != 'unknown':
                headers['User-Agent'] = f"{self.user_agent} (Client-IP: {client_ip})"
            
            # Делаем запрос
            start_time = datetime.datetime.now()
            response = self.session.get(
                url, 
                params=params, 
                timeout=self.timeout,
                headers=headers,
                verify=True
            )
            request_duration = (datetime.datetime.now() - start_time).total_seconds()
            
            # Логируем результат
            safe_log_info(f"OCS API ответ: {response.status_code} за {request_duration:.2f} сек")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    safe_log_info(f"Успешный ответ, размер: {len(str(data))} символов")
                    return data
                except json.JSONDecodeError as e:
                    safe_log_info(f"Ошибка JSON: {e}")
                    return None
            else:
                # Логируем заголовки ответа для диагностики
                safe_log_info(f"Заголовки ответа OCS: {dict(response.headers)}")
                safe_log_info(f"Ошибка {response.status_code}: {response.text[:500]}")
                return None
                
        except requests.exceptions.Timeout as e:
            safe_log_info(f"Таймаут запроса к OCS API: {e}")
            return {"_error": "timeout", "message": "Превышено время ожидания"}
        except requests.exceptions.ConnectionError as e:
            safe_log_info(f"Ошибка соединения с OCS API: {e}")
            return {"_error": "connection", "message": "Ошибка соединения"}
        except Exception as e:
            safe_log_info(f"Ошибка OCS API: {type(e).__name__}: {e}")
            return None
    
    def get_categories(self, client_ip=None):
        safe_log_info("Запрос категорий")
        return self._make_request("catalog/categories", client_ip=client_ip)
    
    def get_shipment_cities(self, client_ip=None):
        safe_log_info("Запрос городов")
        return self._make_request("logistic/shipment/cities", client_ip=client_ip)
    
    def get_products_by_category(self, categories: str, shipment_city: str, client_ip=None, **params):
        endpoint = f"catalog/categories/{categories}/products"
        base_params = {
            'shipmentcity': shipment_city,
            'limit': params.get('limit', 30),
            'offset': params.get('offset', 0)
        }
        
        if 'search' in params:
            base_params['search'] = params['search']
        
        safe_log_info(f"Товары по категории: {categories}")
        return self._make_request(endpoint, params=base_params, client_ip=client_ip)
    
    def search_products(self, search_term: str, shipment_city: str, client_ip=None, **params):
        endpoint = "catalog/categories/all/products"
        base_params = {
            'shipmentcity': shipment_city,
            'search': search_term,
            'limit': params.get('limit', 30)
        }
        
        safe_log_info(f"Поиск: {search_term}")
        return self._make_request(endpoint, params=base_params, client_ip=client_ip)

# Инициализация API
api_key = os.getenv('OCS_API_KEY')

if not api_key:
    logger.info("OCS_API_KEY не найден!")
    # Проверим другие возможные имена
    possible_keys = ['API_KEY', 'OCS_API', 'OCS_KEY']
    for key in possible_keys:
        if os.getenv(key):
            api_key = os.getenv(key)
            logger.info(f"Найден ключ в переменной {key}")
            break

if api_key:
    logger.info(f"API ключ найден (длина: {len(api_key)})")
    ocs_api = OCSAPI(api_key=api_key)
    server_ip = get_server_ip()
    logger.info(f"Сервер запущен на IP: {server_ip}")
else:
    logger.warning("API ключ не найден, демо-режим")
    ocs_api = None
    server_ip = get_server_ip()

# Кэш
cache = {}
CACHE_TTL = 300

# Настройка CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    
    # Добавляем информацию о сервере
    response.headers.add('X-Server-IP', server_ip)
    response.headers.add('X-Server-Location', 'Render.com' if os.environ.get('RENDER') else 'Local')
    
    # Логируем исходящий ответ
    safe_log_info(f"Ответ {response.status_code} для {request.path}")
    
    return response

@app.route('/')
def home():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    # Получаем информацию о IP клиента
    client_info = get_ip_info(client_ip) if client_ip != 'unknown' else None
    
    return jsonify({
        "status": "success", 
        "message": "OCS API Proxy с IP-логированием",
        "environment": "Render.com" if os.environ.get('RENDER') else "Development",
        "server": {
            "ip": server_ip,
            "location": "Render.com" if os.environ.get('RENDER') else "Local"
        },
        "client": {
            "ip": client_ip,
            "info": client_info
        },
        "api_configured": bool(ocs_api),
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/health')
def health_check():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    return jsonify({
        "status": "healthy",
        "server_ip": server_ip,
        "client_ip": client_ip,
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/ipinfo')
def ip_info():
    """Эндпоинт для получения информации об IP"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    client_info = get_ip_info(client_ip) if client_ip != 'unknown' else None
    
    return jsonify({
        "server_ip": server_ip,
        "client_ip": client_ip,
        "client_info": client_info,
        "headers": {
            "x_forwarded_for": request.headers.get('X-Forwarded-For'),
            "x_real_ip": request.headers.get('X-Real-IP'),
            "remote_addr": request.remote_addr
        },
        "render_instance": os.environ.get('RENDER_INSTANCE_ID', 'unknown'),
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/debug')
def debug_info():
    """Подробная отладочная информация"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    # Получаем информацию о домене OCS
    try:
        ocs_ip = socket.gethostbyname('connector.b2b.ocs.ru')
        dns_status = "success"
    except socket.gaierror:
        ocs_ip = "Не удалось разрешить"
        dns_status = "failed"
    except Exception as e:
        ocs_ip = f"Ошибка: {str(e)}"
        dns_status = "error"
    
    return jsonify({
        "server": {
            "ip": server_ip,
            "hostname": socket.gethostname(),
            "platform": sys.platform,
            "python_version": sys.version.split()[0],
            "render_service": os.environ.get('RENDER_SERVICE_NAME', 'unknown'),
            "render_instance": os.environ.get('RENDER_INSTANCE_ID', 'unknown'),
            "render_region": os.environ.get('RENDER_REGION', 'unknown')
        },
        "client": {
            "ip": client_ip,
            "user_agent": request.headers.get('User-Agent'),
            "origin": request.headers.get('Origin'),
            "referer": request.headers.get('Referer')
        },
        "ocs_api": {
            "domain": "connector.b2b.ocs.ru",
            "resolved_ip": ocs_ip,
            "dns_status": dns_status,
            "api_key_configured": bool(api_key),
            "api_key_length": len(api_key) if api_key else 0,
            "api_key_prefix": api_key[:4] + '...' + api_key[-4:] if api_key and len(api_key) > 8 else '***'
        },
        "connection": {
            "x_forwarded_for": request.headers.get('X-Forwarded-For'),
            "x_real_ip": request.headers.get('X-Real-IP'),
            "remote_addr": request.remote_addr,
            "scheme": request.scheme
        },
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/categories')
def get_categories():
    """Получение категорий"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    cache_key = f'categories_{client_ip}'
    
    # Проверяем кэш
    if cache_key in cache:
        cache_time, data = cache[cache_key]
        if (datetime.datetime.now() - cache_time).seconds < CACHE_TTL:
            safe_log_info("Категории из кэша")
            return jsonify({
                "success": True,
                "data": data,
                "cached": True,
                "source": "cache",
                "client_ip": client_ip,
                "server_ip": server_ip
            })
    
    if not ocs_api:
        demo_data = {"result": [
            {"id": "1", "name": "Компьютеры и ноутбуки"},
            {"id": "2", "name": "Комплектующие для ПК"},
            {"id": "3", "name": "Периферия"}
        ]}
        return jsonify({
            "success": True,
            "data": demo_data,
            "cached": False,
            "source": "demo",
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    
    safe_log_info(f"Запрос категорий от клиента {client_ip}")
    categories = ocs_api.get_categories(client_ip=client_ip)
    
    if categories and not categories.get('_error'):
        cache[cache_key] = (datetime.datetime.now(), categories)
        return jsonify({
            "success": True,
            "data": categories,
            "cached": False,
            "source": "ocs_api",
            "client_ip": client_ip,
            "server_ip": server_ip,
            "request_info": {
                "from_client": client_ip,
                "via_server": server_ip,
                "to_ocs": "connector.b2b.ocs.ru"
            }
        })
    else:
        # Пробуем вернуть демо-данные при ошибке
        demo_data = {"result": [
            {"id": "1", "name": "Компьютеры (демо)"},
            {"id": "2", "name": "Комплектующие (демо)"}
        ]}
        return jsonify({
            "success": False,
            "data": demo_data,
            "error": categories.get('message') if categories else "API временно недоступен",
            "client_ip": client_ip,
            "server_ip": server_ip,
            "source": "demo_fallback"
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
                "client_ip": client_ip
            })
    
    if not ocs_api:
        demo_data = ["Красноярск", "Москва", "Новосибирск"]
        return jsonify({
            "success": True,
            "data": demo_data,
            "cached": False,
            "source": "demo",
            "client_ip": client_ip
        })
    
    cities = ocs_api.get_shipment_cities(client_ip=client_ip)
    
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
            "api_error": cities.get('_error') if cities else "unknown",
            "client_ip": client_ip,
            "server_ip": server_ip
        })

@app.route('/api/products/category')
def get_products_by_category():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not ocs_api:
        return jsonify({
            "success": True,
            "data": {"result": []},
            "source": "demo",
            "client_ip": client_ip,
            "server_ip": server_ip
        })
        
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 30, type=int)
    
    safe_log_info(f"Товары: категория={category}, город={shipment_city}, клиент={client_ip}")
    
    if limit > 50:
        limit = 50
    
    products = ocs_api.get_products_by_category(
        categories=category,
        shipment_city=shipment_city,
        client_ip=client_ip,
        limit=limit
    )
    
    if products and not products.get('_error'):
        return jsonify({
            "success": True,
            "data": products,
            "total_count": len(products.get('result', [])),
            "source": "ocs_api",
            "client_ip": client_ip,
            "server_ip": server_ip,
            "connection_path": f"{client_ip} → {server_ip} → OCS API"
        })
    else:
        return jsonify({
            "success": False,
            "data": {"result": []},
            "error": products.get('message') if products else "Ошибка API",
            "source": "error",
            "client_ip": client_ip,
            "server_ip": server_ip
        })

@app.route('/api/products/search')
def search_products():
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not ocs_api:
        return jsonify({
            "success": True,
            "data": {"result": []},
            "source": "demo",
            "client_ip": client_ip
        })
    
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 30, type=int)
    
    if not search_term:
        return jsonify({"success": False, "error": "Не указан поисковый запрос"}), 400
    
    if limit > 50:
        limit = 50
    
    products = ocs_api.search_products(
        search_term=search_term,
        shipment_city=shipment_city,
        client_ip=client_ip,
        limit=limit
    )
    
    if products and not products.get('_error'):
        return jsonify({
            "success": True,
            "data": products,
            "search_term": search_term,
            "total_count": len(products.get('result', [])),
            "source": "ocs_api",
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    else:
        return jsonify({
            "success": False,
            "data": {"result": []},
            "error": products.get('message') if products else "Ошибка API",
            "source": "error",
            "client_ip": client_ip,
            "server_ip": server_ip
        })

@app.route('/api/test/connection')
def test_connection():
    """Тест соединения с OCS API с полной диагностикой"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not api_key:
        return jsonify({
            "success": False,
            "error": "API ключ не настроен",
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    
    results = []
    
    # Тест 1: DNS разрешение
    try:
        ocs_ip = socket.gethostbyname('connector.b2b.ocs.ru')
        results.append({
            "test": "dns_resolution",
            "status": "success",
            "ocs_domain": "connector.b2b.ocs.ru",
            "resolved_ip": ocs_ip
        })
    except socket.gaierror as e:
        results.append({
            "test": "dns_resolution",
            "status": "failed",
            "error": f"DNS ошибка: {str(e)}"
        })
    except Exception as e:
        results.append({
            "test": "dns_resolution",
            "status": "failed",
            "error": str(e)
        })
    
    # Тест 2: Пинг (TCP соединение)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(('connector.b2b.ocs.ru', 443))
        sock.close()
        results.append({
            "test": "tcp_connection",
            "status": "success",
            "port": 443
        })
    except socket.timeout as e:
        results.append({
            "test": "tcp_connection",
            "status": "failed",
            "error": f"Таймаут соединения: {str(e)}"
        })
    except ConnectionRefusedError as e:
        results.append({
            "test": "tcp_connection",
            "status": "failed",
            "error": f"Соединение отклонено: {str(e)}"
        })
    except Exception as e:
        results.append({
            "test": "tcp_connection",
            "status": "failed",
            "error": str(e)
        })
    
    # Тест 3: HTTP запрос к API
    try:
        start_time = datetime.datetime.now()
        response = requests.get(
            "https://connector.b2b.ocs.ru/api/v2/catalog/categories",
            headers={
                'accept': 'application/json',
                'X-API-Key': api_key,
                'User-Agent': f'Connection-Test/1.0 (Server: {server_ip}, Client: {client_ip})'
            },
            timeout=5,
            params={'limit': 1}
        )
        duration = (datetime.datetime.now() - start_time).total_seconds()
        
        results.append({
            "test": "api_request",
            "status": "success" if response.status_code == 200 else "failed",
            "status_code": response.status_code,
            "duration_seconds": duration,
            "response_size": len(response.text)
        })
    except requests.exceptions.Timeout as e:
        results.append({
            "test": "api_request",
            "status": "failed",
            "error": "Таймаут запроса",
            "error_type": "Timeout"
        })
    except requests.exceptions.ConnectionError as e:
        results.append({
            "test": "api_request",
            "status": "failed",
            "error": "Ошибка соединения",
            "error_type": "ConnectionError"
        })
    except Exception as e:
        results.append({
            "test": "api_request",
            "status": "failed",
            "error": str(e),
            "error_type": type(e).__name__
        })
    
    # Анализ результатов
    all_success = all(r['status'] == 'success' for r in results)
    
    return jsonify({
        "success": all_success,
        "tests": results,
        "client_ip": client_ip,
        "server_ip": server_ip,
        "connection_path": f"Client: {client_ip} → Server: {server_ip} → OCS API",
        "timestamp": datetime.datetime.now().isoformat(),
        "diagnosis": "Проверка блокировки: " + (
            "OCS API доступен" if all_success else 
            "Возможна блокировка со стороны OCS или проблемы с сетью"
        )
    })

@app.errorhandler(Exception)
def handle_exception(e):
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    safe_log_info(f"Необработанное исключение: {type(e).__name__}: {e}")
    
    return jsonify({
        "success": False,
        "error": str(e),
        "type": type(e).__name__,
        "client_ip": client_ip,
        "server_ip": server_ip,
        "timestamp": datetime.datetime.now().isoformat()
    }), 500

if __name__ == '__main__':
    # Теперь безопасно добавляем фильтр IP
    logger.addFilter(IPLogFilter())
    
    port = int(os.environ.get('PORT', 10000))
    
    # Получаем и логируем информацию о сервере при запуске
    server_ip = get_server_ip()
    logger.info(f"Сервер запущен на порту {port}")
    logger.info(f"Внешний IP сервера: {server_ip}")
    logger.info(f"Окружение: {'Render.com' if os.environ.get('RENDER') else 'Development'}")
    
    app.run(host='0.0.0.0', port=port, debug=False)