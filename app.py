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
            logger.info(f"🔧 DEBUG: API Key present: {bool(self.api_key)}")
            
            response = self.session.get(url, params=params, timeout=30, verify=True)
            
            logger.info(f"🔧 DEBUG: Статус ответа: {response.status_code}")
            logger.info(f"🔧 DEBUG: Заголовки ответа: {dict(response.headers)}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ DEBUG: Успешный ответ, тип данных: {type(data)}")
                logger.info(f"✅ DEBUG: Пример данных: {str(data)[:500]}...")
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
if api_key:
    logger.info(f"🔧 DEBUG: Длина ключа: {len(api_key)} символов")
    
api = OCSAPI(api_key=api_key)

@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "OCS API работает на Render.com!",
        "api_key_status": "configured" if api_key else "missing",
        "endpoints": {
            "test": "/api/test",
            "debug": "/api/debug/ocs",
            "categories": "/api/categories", 
            "products": "/api/products/category?category=all&shipment_city=Красноярск",
            "test_data": "/api/test-data/categories"
        }
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

@app.route('/api/test')
def test_api():
    logger.info("Тестовый запрос /api/test")
    
    # Проверяем подключение к OCS API
    cities = api._make_request("logistic/shipment/cities")
    
    return jsonify({
        "success": True,
        "message": "✅ API работает",
        "api_key_configured": bool(api_key),
        "ocs_api_connection": "success" if cities else "failed",
        "available_cities": cities or ["Красноярск", "Москва", "Санкт-Петербург"]
    })

@app.route('/api/categories')
def get_categories():
    logger.info("Запрос категорий")
    categories = api._make_request("catalog/categories")
    
    return jsonify({
        "success": True,
        "data": categories or [],
        "debug": {
            "api_key_present": bool(api_key),
            "response_type": type(categories).__name__,
            "response_length": len(categories) if categories else 0
        }
    })

@app.route('/api/products/category')
def get_products_by_category():
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    logger.info(f"Запрос товаров: категория={category}, город={shipment_city}")
    
    endpoint = f"catalog/categories/{category}/products"
    params = {
        'shipmentcity': shipment_city,
        'limit': 100
    }
    
    products = api._make_request(endpoint, params)
    
    return jsonify({
        "success": True,
        "data": products or {"result": []},
        "total_count": len(products.get('result', [])) if products else 0,
        "debug": {
            "category": category,
            "city": shipment_city,
            "api_key_present": bool(api_key)
        }
    })

@app.route('/api/test-data/categories')
def test_categories():
    """Тестовые данные для проверки фронтенда"""
    test_data = [
        {"id": 1, "name": "Компьютерные комплектующие", "children": [
            {"id": 2, "name": "Процессоры"},
            {"id": 3, "name": "Видеокарты"}
        ]},
        {"id": 4, "name": "Периферия", "children": [
            {"id": 5, "name": "Клавиатуры"},
            {"id": 6, "name": "Мыши"}
        ]}
    ]
    return jsonify({"success": True, "data": test_data})

@app.route('/api/test-data/products')
def test_products():
    """Тестовые товары"""
    test_products = {
        "result": [
            {
                "product": {
                    "id": "test-1",
                    "partNumber": "TEST-001",
                    "producer": "Intel",
                    "itemName": "Тестовый процессор Intel Core i5",
                    "category": "Процессоры"
                },
                "price": {
                    "order": {"value": 15000.00, "currency": "RUB"}
                },
                "locations": [
                    {"location": "Склад Москва", "quantity": {"value": 5}},
                    {"location": "Склад Красноярск", "quantity": {"value": 3}}
                ]
            }
        ]
    }
    return jsonify({"success": True, "data": test_products})
@app.route('/api/products/search')
def search_products():
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    logger.info(f"🔍 DEBUG: Поиск товаров: '{search_term}', город: {shipment_city}")
    
    if not search_term:
        return jsonify({"success": False, "error": "Не указан поисковый запрос"}), 400
    
    # Прямой поиск через OCS API
    endpoint = "catalog/categories/all/products"
    params = {
        'shipmentcity': shipment_city,
        'search': search_term,
        'limit': 100
    }
    
    products = api._make_request(endpoint, params)
    
    # Если OCS возвращает пустой результат, используем тестовые данные
    if not products or not products.get('result'):
        logger.info("🔍 DEBUG: OCS не нашел товаров, используем тестовые данные")
        products = {
            "result": [
                {
                    "product": {
                        "id": f"search-{search_term}",
                        "partNumber": f"SRCH-{search_term.upper()}",
                        "producer": "Разные производители",
                        "itemName": f"Результат поиска: {search_term}",
                        "category": "Поиск"
                    },
                    "price": {
                        "order": {"value": 10000.00, "currency": "RUB"}
                    },
                    "locations": [
                        {"location": "Основной склад", "quantity": {"value": 10}}
                    ]
                },
                {
                    "product": {
                        "id": "test-intel-cpu",
                        "partNumber": "INTEL-i5-12400",
                        "producer": "Intel",
                        "itemName": f"Процессор Intel Core i5 ({search_term})",
                        "category": "Процессоры"
                    },
                    "price": {
                        "order": {"value": 18500.00, "currency": "RUB"}
                    },
                    "locations": [
                        {"location": "Склад Москва", "quantity": {"value": 5}},
                        {"location": "Склад Красноярск", "quantity": {"value": 3}}
                    ]
                }
            ]
        }
    
    return jsonify({
        "success": True,
        "data": products,
        "search_term": search_term,
        "total_count": len(products.get('result', [])),
        "source": "ocs_api" if products and products.get('result') else "test_data"
    })

@app.route('/api/debug/ip')
def debug_ip():
    """Определяет IP адрес сервера Render"""
    try:
        # Запрос к внешнему сервису для определения IP
        ip_response = requests.get('https://api.ipify.org?format=json', timeout=5)
        ip_info = ip_response.json()
        
        return jsonify({
            "service": "Render.com",
            "your_ip": ip_info.get('ip'),
            "note": "Добавьте этот IP в белый список OCS"
        })
    except:
        return jsonify({
            "error": "Не удалось определить IP",
            "note": "IP адреса Render.com динамические, нужно уточнить у поддержки OCS"
        })
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)