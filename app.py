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
def get_categories():
    logger.info("Запрос категорий")
    
    # Пробуем получить реальные категории от OCS
    categories = api._make_request("catalog/categories")
    
    # Если OCS не отвечает или возвращает пустой результат, используем тестовые данные
    if not categories:
        logger.info("Используем тестовые категории")
        categories = TEST_CATEGORIES
    
    return jsonify({
        "success": True,
        "data": categories,
        "source": "ocs_api" if categories and categories != TEST_CATEGORIES else "test_data",
        "total_count": len(categories) if categories else 0
    })

@app.route('/api/products/category')
def get_products_by_category():
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    # Исправляем undefined категорию
    if category == 'undefined' or not category:
        category = 'all'
    
    logger.info(f"Запрос товаров: категория='{category}', город='{shipment_city}'")
    
    # Пробуем получить реальные товары от OCS
    endpoint = f"catalog/categories/{category}/products"
    params = {
        'shipmentcity': shipment_city,
        'limit': 100
    }
    
    products = api._make_request(endpoint, params)
    
    # Если OCS не отвечает или возвращает пустой результат, используем тестовые данные
    if not products or not products.get('result'):
        logger.info("Используем тестовые товары")
        products = TEST_PRODUCTS
    
    return jsonify({
        "success": True,
        "data": products,
        "total_count": len(products.get('result', [])),
        "source": "ocs_api" if products and products != TEST_PRODUCTS else "test_data",
        "debug": {
            "requested_category": category,
            "city": shipment_city
        }
    })

@app.route('/api/products/search')
def search_products():
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    logger.info(f"Поиск товаров: запрос='{search_term}', город='{shipment_city}'")
    
    if not search_term:
        return jsonify({"success": False, "error": "Не указан поисковый запрос"}), 400
    
    # Пробуем поиск через OCS API
    endpoint = "catalog/categories/all/products"
    params = {
        'shipmentcity': shipment_city,
        'search': search_term,
        'limit': 100
    }
    
    products = api._make_request(endpoint, params)
    
    # Фильтруем тестовые товары по поисковому запросу
    filtered_test_products = {
        "result": [
            product for product in TEST_PRODUCTS["result"]
            if search_term.lower() in product["product"]["itemName"].lower() or
               search_term.lower() in product["product"]["producer"].lower() or
               search_term.lower() in product["product"]["category"].lower()
        ]
    }
    
    # Если OCS не нашел товаров, используем отфильтрованные тестовые данные
    if not products or not products.get('result'):
        products = filtered_test_products
        source = "test_data"
    else:
        source = "ocs_api"
    
    return jsonify({
        "success": True,
        "data": products,
        "search_term": search_term,
        "total_count": len(products.get('result', [])),
        "source": source
    })

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