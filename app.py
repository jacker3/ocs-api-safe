import os
import requests
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

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
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"🔧 DEBUG: Запрос к OCS API: {url}")
            logger.info(f"🔧 DEBUG: Параметры: {params}")
            
            response = self.session.get(url, params=params, timeout=30, verify=True)
            
            logger.info(f"🔧 DEBUG: Статус ответа: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ DEBUG: Успешный ответ, данные: {len(data) if isinstance(data, list) else 'object'}")
                return data
            elif response.status_code == 401:
                logger.error("❌ DEBUG: 401 Unauthorized - Неверный API ключ")
                return None
            elif response.status_code == 403:
                logger.error("❌ DEBUG: 403 Forbidden - Нет доступа")
                return None
            else:
                logger.error(f"❌ DEBUG: HTTP {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("❌ DEBUG: Таймаут запроса")
            return None
        except requests.exceptions.SSLError as e:
            logger.error(f"❌ DEBUG: SSL ошибка: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ DEBUG: Исключение: {e}")
            return None

# Инициализация API
api_key = os.getenv('OCS_API_KEY')
logger.info(f"🔧 DEBUG: API ключ из окружения: {'***установлен***' if api_key else 'НЕ НАЙДЕН!'}")
api = OCSAPI(api_key=api_key)

# Тестовые данные для разработки
TEST_CATEGORIES = [
    {
        "id": 1,
        "name": "Компьютерные комплектующие",
        "children": [
            {"id": 2, "name": "Процессоры", "productCount": 45},
            {"id": 3, "name": "Видеокарты", "productCount": 23},
            {"id": 4, "name": "Материнские платы", "productCount": 15},
            {"id": 5, "name": "Оперативная память", "productCount": 32}
        ]
    },
    {
        "id": 6,
        "name": "Периферия",
        "children": [
            {"id": 7, "name": "Клавиатуры", "productCount": 28},
            {"id": 8, "name": "Мыши", "productCount": 35},
            {"id": 9, "name": "Мониторы", "productCount": 18}
        ]
    },
    {
        "id": 10,
        "name": "Компьютеры и ноутбуки",
        "children": [
            {"id": 11, "name": "Системные блоки", "productCount": 12},
            {"id": 12, "name": "Ноутбуки", "productCount": 25},
            {"id": 13, "name": "Моноблоки", "productCount": 8}
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
        },
        {
            "product": {
                "id": "test-3",
                "partNumber": "KING-16GB-DDR4",
                "producer": "Kingston",
                "itemName": "Оперативная память Kingston 16GB DDR4",
                "category": "Оперативная память"
            },
            "price": {
                "order": {"value": 3500.00, "currency": "RUB"}
            },
            "locations": [
                {"location": "Склад Красноярск", "quantity": {"value": 25}}
            ]
        },
        {
            "product": {
                "id": "test-4",
                "partNumber": "LOGITECH-K120",
                "producer": "Logitech",
                "itemName": "Клавиатура Logitech K120",
                "category": "Клавиатуры"
            },
            "price": {
                "order": {"value": 1200.00, "currency": "RUB"}
            },
            "locations": [
                {"location": "Склад Москва", "quantity": {"value": 50}},
                {"location": "Склад Красноярск", "quantity": {"value": 15}}
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
        "endpoints": {
            "test": "/api/test",
            "categories": "/api/categories", 
            "products": "/api/products/category?category=all&shipment_city=Красноярск",
            "search": "/api/products/search?q=процессор&shipment_city=Красноярск",
            "test_data": "/api/test-products"
        }
    })

@app.route('/api/test')
def test_api():
    logger.info("Тестовый запрос /api/test")
    
    # Проверяем подключение к OCS API
    cities = api._make_request("logistic/shipment/cities")
    
    return jsonify({
        "success": True,
        "message": "✅ API работает корректно",
        "api_key_configured": bool(api_key),
        "ocs_api_connection": "success" if cities else "failed",
        "available_cities": cities or ["Красноярск", "Москва", "Санкт-Петербург"],
        "environment": "production"
    })

@app.route('/api/categories')
def get_categories(self):
        """Получение дерева товарных категорий"""
        return self._make_request("catalog/categories")

@app.route('/api/products/category')
def get_products_by_category(self, categories: str, shipment_city: str, **params):
        """Получение информации о товарах по категориям"""
        endpoint = f"catalog/categories/{categories}/products"
        params['shipmentcity'] = shipment_city
        # Ограничиваем количество для производительности
        params['limit'] = params.get('limit', 100)
        return self._make_request(endpoint, params=params)

@app.route('/api/products/search')
def search_products(self, search_term: str, shipment_city: str, **params):
        """Поиск товаров по названию"""
        endpoint = f"catalog/categories/all/products"
        params['shipmentcity'] = shipment_city
        params['search'] = search_term
        params['limit'] = params.get('limit', 100)
        return self._make_request(endpoint, params=params)

@app.route('/api/test-products')
def test_products():
    """Endpoint с тестовыми товарами для разработки"""
    return jsonify({
        "success": True,
        "data": TEST_PRODUCTS,
        "total_count": len(TEST_PRODUCTS["result"]),
        "source": "test_data"
    })

@app.route('/api/debug/ocs')
def debug_ocs_connection():
    """Диагностика подключения к OCS API"""
    api_key = os.getenv('OCS_API_KEY')
    test_url = "https://connector.b2b.ocs.ru/api/v2/catalog/categories"
    
    debug_info = {
        "api_key_present": bool(api_key),
        "api_key_length": len(api_key) if api_key else 0,
        "test_url": test_url,
        "render_service": "ocs-api-safe.onrender.com"
    }
    
    try:
        headers = {
            'accept': 'application/json',
            'X-API-Key': api_key or 'missing'
        }
        
        response = requests.get(test_url, headers=headers, timeout=10)
        debug_info.update({
            "ocs_response_status": response.status_code,
            "ocs_response_body_preview": response.text[:200] if response.text else "Empty response"
        })
        
    except Exception as e:
        debug_info["error"] = str(e)
    
    return jsonify(debug_info)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)