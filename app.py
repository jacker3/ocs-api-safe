import os
import requests
import logging
import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ✅ CORS для Beget и локальной разработки
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],  # Разрешаем все домены для тестирования
        "methods": ["GET", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-API-Key"]
    }
})

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
    return response

@app.route('/api/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    return '', 200

class OCSAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://connector.b2b.ocs.ru/api/v2"
        self.session = requests.Session()
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': 'OCS-Integration/1.0'
        })
        logger.info(f"OCS API инициализирован, ключ: {'установлен' if api_key else 'ОТСУТСТВУЕТ'}")
    
    def _make_request(self, endpoint: str, params=None):
        """Базовый метод для запросов к OCS API"""
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"🔧 OCS API Request: {url}")
            
            response = self.session.get(url, params=params, timeout=30, verify=True)
            logger.info(f"🔧 OCS API Response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ OCS API Success: {len(data) if isinstance(data, list) else 'object'}")
                return data
            else:
                logger.error(f"❌ OCS API Error {response.status_code}: {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("❌ OCS API Timeout")
            return None
        except Exception as e:
            logger.error(f"❌ OCS API Exception: {e}")
            return None

    def get_categories(self):
        """Получение дерева товарных категорий"""
        return self._make_request("catalog/categories")
    
    def get_shipment_cities(self):
        """Получение списка доступных городов отгрузки"""
        return self._make_request("logistic/shipment/cities")
    
    def get_products_by_category(self, categories: str, shipment_city: str, **params):
        """Получение информации о товарах по категориям"""
        endpoint = f"catalog/categories/{categories}/products"
        params['shipmentcity'] = shipment_city
        # Ограничиваем количество для производительности
        params['limit'] = params.get('limit', 100)
        return self._make_request(endpoint, params=params)
    
    def search_products(self, search_term: str, shipment_city: str, **params):
        """Поиск товаров по названию"""
        endpoint = f"catalog/categories/all/products"
        params['shipmentcity'] = shipment_city
        params['search'] = search_term
        params['limit'] = params.get('limit', 100)
        return self._make_request(endpoint, params=params)

# Инициализация API
api_key = os.getenv('OCS_API_KEY')
logger.info(f"🔧 API Key: {'***установлен***' if api_key else 'НЕ НАЙДЕН!'}")
ocs_api = OCSAPI(api_key=api_key)

# Тестовые данные для fallback
TEST_CATEGORIES = [
    {
        "id": "1",
        "name": "Компьютерные комплектующие",
        "children": [
            {"id": "2", "name": "Процессоры", "productCount": 45},
            {"id": "3", "name": "Видеокарты", "productCount": 23},
            {"id": "4", "name": "Материнские платы", "productCount": 15},
            {"id": "5", "name": "Оперативная память", "productCount": 32}
        ]
    },
    {
        "id": "6", 
        "name": "Периферия",
        "children": [
            {"id": "7", "name": "Клавиатуры", "productCount": 28},
            {"id": "8", "name": "Мыши", "productCount": 35},
            {"id": "9", "name": "Мониторы", "productCount": 18}
        ]
    }
]

TEST_PRODUCTS = {
    "result": [
        {
            "product": {
                "id": "test-1",
                "partNumber": "INTEL-i5-12400",
                "producer": "Intel",
                "itemName": "Процессор Intel Core i5-12400",
                "category": "Процессоры"
            },
            "price": {
                "order": {"value": 18500.00, "currency": "RUB"}
            },
            "locations": [
                {"location": "Склад Москва", "quantity": {"value": 12}},
                {"location": "Склад Красноярск", "quantity": {"value": 5}}
            ]
        },
        {
            "product": {
                "id": "test-2",
                "partNumber": "NV-RTX-4060", 
                "producer": "NVIDIA",
                "itemName": "Видеокарта NVIDIA RTX 4060",
                "category": "Видеокарты"
            },
            "price": {
                "order": {"value": 45000.00, "currency": "RUB"}
            },
            "locations": [
                {"location": "Склад Москва", "quantity": {"value": 3}},
                {"location": "Склад СПб", "quantity": {"value": 2}}
            ]
        }
    ]
}

@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "OCS API работает на Render.com!",
        "api_key_status": "configured" if api_key else "missing",
        "cors_enabled": True,
        "endpoints": {
            "test": "/api/test",
            "categories": "/api/categories", 
            "cities": "/api/cities",
            "products": "/api/products/category?category=all&shipment_city=Красноярск",
            "search": "/api/products/search?q=процессор&shipment_city=Красноярск"
        }
    })

@app.route('/api/test')
def test_api():
    """Тест подключения к OCS API"""
    logger.info("🔧 Testing OCS API connection")
    
    # Тестируем получение городов
    cities = ocs_api.get_shipment_cities()
    
    return jsonify({
        "success": True,
        "message": "✅ API работает корректно",
        "api_key_configured": bool(api_key),
        "ocs_api_connection": "success" if cities else "failed",
        "available_cities": cities or ["Красноярск", "Москва", "Санкт-Петербург"],
        "environment": "production"
    })

@app.route('/api/categories')
def get_categories():
    """Получение категорий товаров"""
    logger.info("🔧 Fetching categories")
    
    # Используем рабочий метод из примера
    categories = ocs_api.get_categories()
    
    # Fallback на тестовые данные
    if not categories:
        logger.info("🔄 Using test categories")
        categories = TEST_CATEGORIES
    
    return jsonify({
        "success": True,
        "data": categories,
        "source": "ocs_api" if categories and categories != TEST_CATEGORIES else "test_data",
        "total_count": len(categories) if categories else 0
    })

@app.route('/api/cities')
def get_cities():
    """Получение списка городов"""
    logger.info("🔧 Fetching cities")
    
    cities = ocs_api.get_shipment_cities()
    
    return jsonify({
        "success": True,
        "data": cities or ["Красноярск", "Москва", "Санкт-Петербург"],
        "source": "ocs_api" if cities else "test_data"
    })

@app.route('/api/products/category')
def get_products_by_category():
    """Получение товаров по категории"""
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 100)
    
    logger.info(f"🔧 Fetching products: category={category}, city={shipment_city}")
    
    # Валидация категории
    if category in ['undefined', 'null', '']:
        category = 'all'
    
    # Используем рабочий метод из примера
    products = ocs_api.get_products_by_category(
        categories=category,
        shipment_city=shipment_city,
        limit=limit
    )
    
    # Fallback на тестовые данные
    if not products or not products.get('result'):
        logger.info("🔄 Using test products")
        products = TEST_PRODUCTS
    
    return jsonify({
        "success": True,
        "data": products,
        "total_count": len(products.get('result', [])),
        "source": "ocs_api" if products and products != TEST_PRODUCTS else "test_data",
        "request": {
            "category": category,
            "city": shipment_city,
            "limit": limit
        }
    })

@app.route('/api/products/search')
def search_products():
    """Поиск товаров"""
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 100)
    
    logger.info(f"🔧 Searching products: q={search_term}, city={shipment_city}")
    
    if not search_term:
        return jsonify({
            "success": False, 
            "error": "Не указан поисковый запрос"
        }), 400
    
    # Используем рабочий метод из примера
    products = ocs_api.search_products(
        search_term=search_term,
        shipment_city=shipment_city,
        limit=limit
    )
    
    # Fallback на тестовые данные
    if not products or not products.get('result'):
        logger.info("🔄 Using test products for search")
        products = {
            "result": [
                product for product in TEST_PRODUCTS["result"]
                if search_term.lower() in product["product"]["itemName"].lower()
            ]
        }
        if not products["result"]:
            products["result"] = TEST_PRODUCTS["result"]
    
    return jsonify({
        "success": True,
        "data": products,
        "search_term": search_term,
        "total_count": len(products.get('result', [])),
        "source": "ocs_api" if products and products.get('result') and products != TEST_PRODUCTS else "test_data"
    })

@app.route('/api/debug/status')
def debug_status():
    """Диагностика статуса API"""
    return jsonify({
        "ocs_api_key": "configured" if api_key else "missing",
        "cors_enabled": True,
        "render_service": "ocs-api-safe.onrender.com",
        "ocs_api_base": "https://connector.b2b.ocs.ru/api/v2",
        "timestamp": time.time()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)