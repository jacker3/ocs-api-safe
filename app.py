import os
import requests
import logging
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from dotenv import load_dotenv
import sys
import datetime
import socket
import threading
import time
import json

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

# Глобальный кэш
cache = {
    'categories': {
        'data': None,
        'timestamp': 0,
        'ttl': 86400,
        'lock': threading.Lock()
    },
    'cities': {
        'data': None,
        'timestamp': 0,
        'ttl': 3600,
        'lock': threading.Lock()
    }
}

# Middleware для логирования IP
@app.before_request
def log_request_info():
    if request.headers.get('X-Forwarded-For'):
        client_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        client_ip = request.headers.get('X-Real-IP')
    else:
        client_ip = request.remote_addr
    
    g.client_ip = client_ip
    
    logger.info(f"Запрос {request.method} {request.path} от {client_ip}")

# Глобальная переменная для IP сервера
SERVER_IP = None

def get_server_ip():
    """Получает внешний IP сервера"""
    global SERVER_IP
    if SERVER_IP:
        return SERVER_IP
    
    try:
        # Сначала пробуем локальный IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            SERVER_IP = s.getsockname()[0]
            s.close()
            logger.info(f"Локальный IP сервера: {SERVER_IP}")
            return SERVER_IP
        except:
            pass
        
        # Если не получилось, пробуем внешние сервисы
        services = [
            'https://api.ipify.org',
            'https://ident.me',
            'https://checkip.amazonaws.com'
        ]
        
        for service in services:
            try:
                response = requests.get(service, timeout=5)
                if response.status_code == 200:
                    SERVER_IP = response.text.strip()
                    logger.info(f"Внешний IP сервера: {SERVER_IP}")
                    return SERVER_IP
            except:
                continue
        
        SERVER_IP = 'unknown'
        return SERVER_IP
    except Exception as e:
        logger.error(f"Ошибка получения IP сервера: {e}")
        SERVER_IP = 'unknown'
        return SERVER_IP

class OCSAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://connector.b2b.ocs.ru/api/"
        
        self.server_ip = get_server_ip()
        logger.info(f"OCSAPI инициализирован. Сервер IP: {self.server_ip}")
        
        # Создаем сессию
        self.session = requests.Session()
        
        # Устанавливаем таймауты для Render
        self.timeout = (10, 30)
        
        # Настройки для больших ответов
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=3
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Правильные заголовки для OCS API
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': f'OCS-Proxy/1.0',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        })
    
    def _make_request(self, endpoint: str, params=None, stream=False):
        """Выполняет запрос к OCS API"""
        try:
            url = f"{self.base_url}/{endpoint}"
            
            logger.info(f"Запрос к OCS API: {endpoint}")
            
            start_time = datetime.datetime.now()
            response = self.session.get(
                url, 
                params=params, 
                timeout=self.timeout,
                verify=True,
                stream=stream
            )
            request_duration = (datetime.datetime.now() - start_time).total_seconds()
            
            logger.info(f"Ответ OCS API: {response.status_code} за {request_duration:.2f}с")
            
            if response.status_code == 200:
                try:
                    # Для больших ответов используем streaming
                    if stream:
                        content = b''
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                content += chunk
                        data = json.loads(content.decode('utf-8'))
                    else:
                        data = response.json()
                    
                    logger.info(f"Успешно получено данных, размер: {len(str(data))} символов")
                    
                    # Логируем структуру данных для отладки
                    if endpoint == "catalog/categories":
                        logger.info(f"Тип данных категорий: {type(data)}")
                        if isinstance(data, list):
                            logger.info(f"Количество категорий: {len(data)}")
                            if len(data) > 0:
                                logger.info(f"Пример категории: {data[0]}")
                        elif isinstance(data, dict):
                            logger.info(f"Ключи в данных: {list(data.keys())}")
                    
                    return data
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка парсинга JSON: {e}")
                    logger.error(f"Текст ответа (первые 500 символов): {response.text[:500]}")
                    return None
                except Exception as e:
                    logger.error(f"Ошибка обработки ответа: {type(e).__name__}: {e}")
                    return None
            else:
                logger.error(f"Ошибка OCS API {response.status_code}: {response.text[:500]}")
                return None
                
        except requests.exceptions.Timeout as e:
            logger.error(f"Таймаут запроса к OCS API: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ошибка подключения к OCS API: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка OCS API: {type(e).__name__}: {e}")
            return None
    
    def get_categories(self):
        """Получение категорий с кэшированием"""
        with cache['categories']['lock']:
            current_time = time.time()
            
            # Проверяем кэш
            if (cache['categories']['data'] is not None and 
                current_time - cache['categories']['timestamp'] < cache['categories']['ttl']):
                logger.info("Возвращаем категории из кэша")
                return cache['categories']['data']
            
            logger.info("Запрос категорий из OCS API")
            # Используем stream=True для больших данных
            data = self._make_request("catalog/categories", stream=True)
            
            if data:
                cache['categories']['data'] = data
                cache['categories']['timestamp'] = current_time
                logger.info(f"Категории сохранены в кэш")
                
                # Логируем детали для отладки
                if isinstance(data, list):
                    logger.info(f"Получено {len(data)} категорий")
                elif isinstance(data, dict):
                    logger.info(f"Получен словарь с ключами: {list(data.keys())}")
            else:
                logger.error("Не удалось получить категории из OCS API")
                # Возвращаем старые данные из кэша, если есть
                if cache['categories']['data']:
                    logger.info("Возвращаем старые данные из кэша")
                    return cache['categories']['data']
            
            return data
    
    def get_shipment_cities(self):
        """Получение городов с кэшированием"""
        with cache['cities']['lock']:
            current_time = time.time()
            
            # Проверяем кэш
            if (cache['cities']['data'] is not None and 
                current_time - cache['cities']['timestamp'] < cache['cities']['ttl']):
                logger.info("Возвращаем города из кэша")
                return cache['cities']['data']
            
            logger.info("Запрос городов из OCS API")
            data = self._make_request("logistic/shipment/cities")
            
            if data:
                cache['cities']['data'] = data
                cache['cities']['timestamp'] = current_time
                logger.info(f"Города сохранены в кэш, тип данных: {type(data)}")
            else:
                logger.error("Не удалось получить города из OCS API")
                if cache['cities']['data']:
                    logger.info("Возвращаем старые данные из кэша")
                    return cache['cities']['data']
            
            return data
    
    def get_products_by_category(self, category_id: str, shipment_city: str, **params):
        """Получение товаров по категории"""
        endpoint = f"catalog/categories/{category_id}/products"
        
        base_params = {
            'shipmentcity': shipment_city,
            'limit': params.get('limit', 50)  # Уменьшаем лимит
        }
        
        if 'search' in params:
            base_params['search'] = params['search']
        
        logger.info(f"Товары по категории: {category_id}, город: {shipment_city}")
        return self._make_request(endpoint, params=base_params)
    
    def search_products(self, search_term: str, shipment_city: str, **params):
        """Поиск товаров"""
        endpoint = "catalog/categories/all/products"
        
        base_params = {
            'shipmentcity': shipment_city,
            'search': search_term,
            'limit': params.get('limit', 50)
        }
        
        logger.info(f"Поиск: {search_term}, город: {shipment_city}")
        return self._make_request(endpoint, params=base_params)

# Инициализация API
api_key = os.getenv('OCS_API_KEY')

if not api_key:
    logger.error("OCS_API_KEY не найден!")
    possible_keys = ['API_KEY', 'OCS_API', 'OCS_KEY']
    for key in possible_keys:
        if os.getenv(key):
            api_key = os.getenv(key)
            logger.info(f"Найден ключ в переменной {key}")
            break

if api_key:
    logger.info(f"API ключ найден (длина: {len(api_key)})")
    ocs_api = OCSAPI(api_key=api_key)
else:
    logger.error("API ключ не найден! Работа в демо-режиме.")
    ocs_api = None

server_ip = get_server_ip()
logger.info(f"Сервер запущен на IP: {server_ip}")

# Настройка CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    
    # Добавляем информацию о сервере
    response.headers.add('X-Server-IP', server_ip)
    
    logger.info(f"Ответ {response.status_code} для {request.path}")
    
    return response

# Фоновая загрузка данных
def preload_data():
    """Предзагрузка данных при старте"""
    if ocs_api:
        logger.info("Запуск фоновой загрузки данных...")
        try:
            # Загружаем города
            cities = ocs_api.get_shipment_cities()
            if cities:
                logger.info("Города предзагружены")
            
            # Загружаем категории в отдельном потоке
            def load_categories():
                try:
                    categories = ocs_api.get_categories()
                    if categories:
                        logger.info("Категории предзагружены")
                    else:
                        logger.warning("Не удалось предзагрузить категории")
                except Exception as e:
                    logger.error(f"Ошибка предзагрузки категорий: {e}")
            
            threading.Thread(target=load_categories, daemon=True).start()
            
        except Exception as e:
            logger.error(f"Ошибка предзагрузки данных: {e}")

# Запускаем предзагрузку
preload_data()

# Главная страница
@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "OCS API Proxy",
        "server_ip": server_ip,
        "api_configured": bool(ocs_api),
        "cache_status": {
            "categories": cache['categories']['data'] is not None,
            "cities": cache['cities']['data'] is not None
        },
        "endpoints": [
            "/api/categories",
            "/api/cities",
            "/api/products/category?category=all&shipment_city=Красноярск",
            "/api/products/search?q=ноутбук&shipment_city=Красноярск",
            "/api/cache/status"
        ]
    })

@app.route('/api/categories')
def get_categories():
    """Получение категорий"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not ocs_api:
        return jsonify({
            "success": True,
            "data": [
                {"id": "all", "name": "Все товары"},
                {"id": "1", "name": "Компьютеры и ноутбуки"},
                {"id": "2", "name": "Комплектующие"}
            ],
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_mode": True
        })
    
    logger.info(f"Запрос категорий от {client_ip}")
    
    # Проверяем кэш
    with cache['categories']['lock']:
        if cache['categories']['data'] is not None:
            logger.info("Возвращаем категории из кэша")
            return jsonify({
                "success": True,
                "data": cache['categories']['data'],
                "client_ip": client_ip,
                "server_ip": server_ip,
                "cached": True,
                "cache_age": int(time.time() - cache['categories']['timestamp'])
            })
    
    # Если нет в кэше, получаем данные
    categories = ocs_api.get_categories()
    
    if categories is not None:
        # Проверяем формат данных
        if isinstance(categories, dict) and 'error' in categories:
            logger.error(f"Ошибка в данных категорий: {categories}")
            return jsonify({
                "success": False,
                "error": categories.get('error', 'Unknown error'),
                "client_ip": client_ip,
                "server_ip": server_ip
            }), 500
        
        return jsonify({
            "success": True,
            "data": categories,
            "client_ip": client_ip,
            "server_ip": server_ip,
            "data_type": type(categories).__name__,
            "data_length": len(str(categories)) if categories else 0
        })
    else:
        # Если данные не получены, возвращаем демо-данные
        logger.warning("Возвращаем демо-категории")
        return jsonify({
            "success": True,
            "data": [
                {"id": "all", "name": "Все товары"},
                {"id": "computers", "name": "Компьютеры"},
                {"id": "network", "name": "Сетевое оборудование"}
            ],
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_fallback": True,
            "note": "Using demo data while OCS API is loading"
        })

@app.route('/api/cities')
def get_cities():
    """Получение городов"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not ocs_api:
        return jsonify({
            "success": True,
            "data": [
                {"id": "1", "name": "Красноярск"},
                {"id": "2", "name": "Москва"},
                {"id": "3", "name": "Владивосток"}
            ],
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_mode": True
        })
    
    cities = ocs_api.get_shipment_cities()
    
    if cities is not None:
        return jsonify({
            "success": True,
            "data": cities,
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    else:
        return jsonify({
            "success": False,
            "error": "Не удалось получить города",
            "client_ip": client_ip,
            "server_ip": server_ip
        }), 500

@app.route('/api/products/category')
def get_products_by_category():
    """Получение товаров по категории"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not ocs_api:
        return jsonify({
            "success": True,
            "data": {
                "products": [
                    {
                        "id": "1",
                        "name": "Демо товар",
                        "price": 10000,
                        "quantity": 5
                    }
                ]
            },
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_mode": True
        })
    
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 50, type=int)
    
    logger.info(f"Товары: категория={category}, город={shipment_city}")
    
    products = ocs_api.get_products_by_category(
        category_id=category,
        shipment_city=shipment_city,
        limit=limit
    )
    
    if products is not None:
        return jsonify({
            "success": True,
            "data": products,
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    else:
        return jsonify({
            "success": False,
            "error": "Не удалось получить товары",
            "client_ip": client_ip,
            "server_ip": server_ip
        }), 500

@app.route('/api/products/search')
def search_products():
    """Поиск товаров"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not ocs_api:
        return jsonify({
            "success": True,
            "data": {
                "products": [
                    {
                        "id": "1",
                        "name": "Демо товар",
                        "price": 12000,
                        "quantity": 2
                    }
                ]
            },
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_mode": True
        })
    
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 50, type=int)
    
    if not search_term:
        return jsonify({
            "success": False, 
            "error": "Не указан поисковый запрос",
            "client_ip": client_ip,
            "server_ip": server_ip
        }), 400
    
    products = ocs_api.search_products(
        search_term=search_term,
        shipment_city=shipment_city,
        limit=limit
    )
    
    if products is not None:
        return jsonify({
            "success": True,
            "data": products,
            "search_term": search_term,
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    else:
        return jsonify({
            "success": False,
            "error": "Не удалось найти товары",
            "client_ip": client_ip,
            "server_ip": server_ip
        }), 500

@app.route('/api/cache/status')
def cache_status():
    """Статус кэша"""
    return jsonify({
        "categories": {
            "has_data": cache['categories']['data'] is not None,
            "age_seconds": int(time.time() - cache['categories']['timestamp']) if cache['categories']['data'] else None,
            "ttl_seconds": cache['categories']['ttl']
        },
        "cities": {
            "has_data": cache['cities']['data'] is not None,
            "age_seconds": int(time.time() - cache['cities']['timestamp']) if cache['cities']['data'] else None,
            "ttl_seconds": cache['cities']['ttl']
        },
        "server_ip": server_ip,
        "ocs_api_configured": bool(ocs_api)
    })

@app.route('/api/cache/clear')
def clear_cache():
    """Сброс кэша"""
    with cache['categories']['lock']:
        cache['categories']['data'] = None
        cache['categories']['timestamp'] = 0
    
    with cache['cities']['lock']:
        cache['cities']['data'] = None
        cache['cities']['timestamp'] = 0
    
    # Перезагружаем данные
    if ocs_api:
        threading.Thread(target=preload_data, daemon=True).start()
    
    return jsonify({
        "success": True,
        "message": "Cache cleared. Reloading data.",
        "server_ip": server_ip
    })

# Эндпоинт для тестирования OCS API
@app.route('/api/test/ocs')
def test_ocs_api():
    """Тест подключения к OCS API"""
    if not ocs_api:
        return jsonify({
            "success": False,
            "error": "API not configured"
        })
    
    try:
        # Тестовый запрос
        test_url = f"{ocs_api.base_url}/catalog/categories"
        response = ocs_api.session.get(test_url, params={'limit': 1}, timeout=10)
        
        return jsonify({
            "success": True,
            "status": response.status_code,
            "headers": dict(response.headers),
            "elapsed_seconds": response.elapsed.total_seconds(),
            "sample_data": response.json() if response.status_code == 200 else response.text[:200]
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "type": type(e).__name__
        })

# Обработчик ошибок
@app.errorhandler(Exception)
def handle_exception(e):
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    logger.error(f"Ошибка: {type(e).__name__}: {e}")
    
    return jsonify({
        "success": False,
        "error": "Internal server error",
        "type": type(e).__name__,
        "client_ip": client_ip,
        "server_ip": server_ip,
        "timestamp": datetime.datetime.now().isoformat()
    }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    logger.info("=" * 60)
    logger.info(f"Запуск OCS Proxy на порту {port}")
    logger.info(f"Сервер IP: {server_ip}")
    logger.info(f"API ключ: {'Настроен' if api_key else 'Не настроен (демо)'}")
    logger.info("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
