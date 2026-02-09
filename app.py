import os
import requests
import logging
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from dotenv import load_dotenv
import sys
import datetime
import socket

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
        # Попробуем получить локальный IP
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
        self.base_url = "https://connector.b2b.ocs.ru/api/v2"
        
        self.server_ip = get_server_ip()
        logger.info(f"OCSAPI инициализирован. Сервер IP: {self.server_ip}")
        
        # Создаем сессию с большими таймаутами
        self.session = requests.Session()
        
        # Большие таймауты как запрошено
        self.timeout = (30, 120)  # 30 секунд на соединение, 120 на чтение
        
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': f'OCS-Proxy/1.0 (Server-IP:{self.server_ip})',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        })
    
    def _make_request(self, endpoint: str, params=None):
        """Выполняет запрос к OCS API с большими таймаутами"""
        try:
            url = f"{self.base_url}/{endpoint}"
            
            logger.info(f"Запрос к OCS API: {endpoint}, параметры: {params}")
            
            start_time = datetime.datetime.now()
            response = self.session.get(
                url, 
                params=params, 
                timeout=self.timeout,
                verify=True
            )
            request_duration = (datetime.datetime.now() - start_time).total_seconds()
            
            logger.info(f"Ответ OCS API: {response.status_code} за {request_duration:.2f}с")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    logger.info(f"Успешно получено данных: {len(str(data))} символов")
                    return data
                except Exception as e:
                    logger.error(f"Ошибка парсинга JSON: {e}")
                    return None
            else:
                logger.error(f"Ошибка OCS API {response.status_code}: {response.text[:500]}")
                return None
                
        except requests.exceptions.Timeout as e:
            logger.error(f"Таймаут запроса к OCS API: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка OCS API: {type(e).__name__}: {e}")
            return None
    
    def get_categories(self):
        """Получение категорий"""
        logger.info("Запрос категорий")
        return self._make_request("catalog/categories")
    
    def get_shipment_cities(self):
        """Получение городов"""
        logger.info("Запрос городов")
        return self._make_request("logistic/shipment/cities")
    
    def get_products_by_category(self, category_id: str, shipment_city: str, **params):
        """Получение товаров по категории"""
        endpoint = f"catalog/categories/{category_id}/products"
        
        base_params = {
            'shipmentcity': shipment_city,
            'limit': params.get('limit', 100)
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
            'limit': params.get('limit', 100)
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

# Главная страница (только для проверки работы)
@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "OCS API Proxy",
        "server_ip": server_ip,
        "api_configured": bool(ocs_api),
        "endpoints": [
            "/api/categories",
            "/api/cities",
            "/api/products/category?category=all&shipment_city=Красноярск",
            "/api/products/search?q=ноутбук&shipment_city=Красноярск"
        ]
    })

# API эндпоинты
@app.route('/api/categories')
def get_categories():
    """Получение категорий"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not ocs_api:
        # Демо-режим
        demo_data = {
            "success": True,
            "data": [
                {"id": "1", "name": "Демо категория 1"},
                {"id": "2", "name": "Демо категория 2"}
            ],
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_mode": True
        }
        return jsonify(demo_data)
    
    logger.info(f"Запрос категорий от {client_ip}")
    categories = ocs_api.get_categories()
    
    if categories:
        return jsonify({
            "success": True,
            "data": categories,
            "client_ip": client_ip,
            "server_ip": server_ip
        })
    else:
        return jsonify({
            "success": False,
            "error": "Не удалось получить категории",
            "client_ip": client_ip,
            "server_ip": server_ip
        }), 500

@app.route('/api/cities')
def get_cities():
    """Получение городов"""
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    if not ocs_api:
        # Демо-режим
        demo_data = {
            "success": True,
            "data": [
                {"id": "1", "name": "Красноярск"},
                {"id": "2", "name": "Москва"},
                {"id": "3", "name": "Владивосток"}
            ],
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_mode": True
        }
        return jsonify(demo_data)
    
    cities = ocs_api.get_shipment_cities()
    
    if cities:
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
    
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 100, type=int)
    search = request.args.get('search', None)
    
    logger.info(f"Товары: категория={category}, город={shipment_city}")
    
    if not ocs_api:
        # Демо-режим
        demo_data = {
            "success": True,
            "data": {
                "products": [
                    {
                        "id": "1",
                        "name": f"Демо товар для категории {category}",
                        "price": 10000,
                        "quantity": 5,
                        "manufacturer": "Demo Manufacturer"
                    },
                    {
                        "id": "2",
                        "name": f"Еще один демо товар {category}",
                        "price": 15000,
                        "quantity": 3,
                        "manufacturer": "Demo Manufacturer"
                    }
                ]
            },
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_mode": True,
            "category": category,
            "shipment_city": shipment_city
        }
        return jsonify(demo_data)
    
    # Подготавливаем параметры
    params = {'limit': limit}
    if search:
        params['search'] = search
    
    products = ocs_api.get_products_by_category(
        category_id=category,
        shipment_city=shipment_city,
        **params
    )
    
    if products:
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
    
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 100, type=int)
    
    if not search_term:
        return jsonify({
            "success": False, 
            "error": "Не указан поисковый запрос",
            "client_ip": client_ip,
            "server_ip": server_ip
        }), 400
    
    if not ocs_api:
        # Демо-режим
        demo_data = {
            "success": True,
            "data": {
                "products": [
                    {
                        "id": "1",
                        "name": f"Демо результат для '{search_term}'",
                        "price": 12000,
                        "quantity": 2,
                        "manufacturer": "Demo Manufacturer"
                    },
                    {
                        "id": "2",
                        "name": f"Еще один результат '{search_term}'",
                        "price": 18000,
                        "quantity": 4,
                        "manufacturer": "Demo Manufacturer"
                    }
                ]
            },
            "search_term": search_term,
            "client_ip": client_ip,
            "server_ip": server_ip,
            "demo_mode": True,
            "shipment_city": shipment_city
        }
        return jsonify(demo_data)
    
    products = ocs_api.search_products(
        search_term=search_term,
        shipment_city=shipment_city,
        limit=limit
    )
    
    if products:
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

# Обработчик ошибок
@app.errorhandler(Exception)
def handle_exception(e):
    client_ip = getattr(g, 'client_ip', 'unknown')
    
    logger.error(f"Ошибка: {type(e).__name__}: {e}")
    
    return jsonify({
        "success": False,
        "error": str(e),
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
    logger.info(f"API ключ: {'Настроен' if api_key else 'Не настроен (демо-режим)'}")
    logger.info("Таймауты: соединение 30с, чтение 120с")
    logger.info("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False)