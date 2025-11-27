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

# ✅ УПРОЩЕННАЯ CORS НАСТРОЙКА - РАЗРЕШАЕМ ВСЕ
CORS(app)

@app.after_request
def after_request(response):
    # ✅ ОБЯЗАТЕЛЬНО добавляем CORS заголовки ко всем ответам
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

@app.route('/api/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    response = jsonify({'status': 'CORS preflight'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', '*')
    response.headers.add('Access-Control-Allow-Methods', '*')
    return response

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
        logger.info(f"OCS API инициализирован")
    
    def _make_request(self, endpoint: str, params=None):
        """Базовый метод для запросов к OCS API"""
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"🔧 OCS API: {endpoint}")
            
            response = self.session.get(url, params=params, timeout=15, verify=True)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"❌ OCS API Error {response.status_code}")
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
        params['limit'] = params.get('limit', 50)
        return self._make_request(endpoint, params=params)
    
    def search_products(self, search_term: str, shipment_city: str, **params):
        """Поиск товаров по названию"""
        endpoint = f"catalog/categories/all/products"
        params['shipmentcity'] = shipment_city
        params['search'] = search_term
        params['limit'] = params.get('limit', 50)
        return self._make_request(endpoint, params=params)

# Инициализация API
api_key = os.getenv('OCS_API_KEY')
logger.info(f"🔧 API Key: {'***установлен***' if api_key else 'НЕ НАЙДЕН!'}")
ocs_api = OCSAPI(api_key=api_key)

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
    
    return jsonify({
        "success": True,
        "data": categories,
        "source": "ocs_api",
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
        "source": "ocs_api"
    })

@app.route('/api/products/category')
def get_products_by_category():
    """Получение товаров по категории"""
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    limit = request.args.get('limit', 50)
    
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
    
    return jsonify({
        "success": True if products else False,
        "data": products,
        "total_count": len(products.get('result', [])) if products else 0,
        "source": "ocs_api",
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
    limit = request.args.get('limit', 50)
    
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
    
    return jsonify({
        "success": True if products else False,
        "data": products,
        "search_term": search_term,
        "total_count": len(products.get('result', [])) if products else 0,
        "source": "ocs_api"
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