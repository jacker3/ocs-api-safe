import os
import requests
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import sys

# Настройка логирования с максимальной детализацией
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
CORS(app)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
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
        logger.debug(f"OCSAPI инициализирован с API ключом: {'установлен' if api_key else 'отсутствует'}")
    
    def _make_request(self, endpoint: str, params=None):
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.debug(f"OCS API Запрос: {url}")
            logger.debug(f"OCS API Параметры: {params}")
            logger.debug(f"OCS API Заголовки: {dict(self.session.headers)}")
            
            # Добавляем timeout и логируем процесс
            response = self.session.get(
                url, 
                params=params, 
                timeout=30,  # Увеличиваем timeout для Render
                verify=True
            )
            
            logger.debug(f"OCS API Статус код: {response.status_code}")
            logger.debug(f"OCS API Заголовки ответа: {dict(response.headers)}")
            logger.debug(f"OCS API Ответ (первые 500 символов): {response.text[:500]}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    logger.debug(f"OCS API Успешный JSON ответ, размер данных: {len(str(data))}")
                    return data
                except Exception as json_error:
                    logger.error(f"OCS API Ошибка парсинга JSON: {json_error}")
                    logger.error(f"OCS API Сырой ответ: {response.text}")
                    return None
            else:
                logger.error(f"OCS API Ошибка HTTP {response.status_code}: {response.text}")
                return None
                
        except requests.exceptions.Timeout as e:
            logger.error(f"OCS API Timeout: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"OCS API ConnectionError: {e}")
            return None
        except requests.exceptions.SSLError as e:
            logger.error(f"OCS API SSLError: {e}")
            return None
        except Exception as e:
            logger.error(f"OCS API Неожиданная ошибка: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"OCS API Traceback: {traceback.format_exc()}")
            return None
    
    def get_categories(self):
        logger.info("Запрос категорий из OCS API")
        result = self._make_request("catalog/categories")
        logger.info(f"Результат запроса категорий: {'успех' if result else 'неудача'}")
        return result
    
    def get_shipment_cities(self):
        logger.info("Запрос городов доставки из OCS API")
        result = self._make_request("logistic/shipment/cities")
        logger.info(f"Результат запроса городов: {'успех' if result else 'неудача'}")
        return result
    
    def get_products_by_category(self, categories: str, shipment_city: str, **params):
        endpoint = f"catalog/categories/{categories}/products"
        params['shipmentcity'] = shipment_city
        params['limit'] = params.get('limit', 50)
        logger.info(f"Запрос товаров по категории: {categories}, город: {shipment_city}")
        return self._make_request(endpoint, params=params)
    
    def search_products(self, search_term: str, shipment_city: str, **params):
        endpoint = f"catalog/categories/all/products"
        params['shipmentcity'] = shipment_city
        params['search'] = search_term
        params['limit'] = params.get('limit', 50)
        logger.info(f"Поиск товаров: {search_term}, город: {shipment_city}")
        return self._make_request(endpoint, params=params)

# Инициализация API с проверкой
api_key = os.getenv('OCS_API_KEY')
logger.info(f"API ключ из переменных окружения: {'установлен' if api_key else 'НЕ НАЙДЕН'}")

if api_key:
    # Проверяем длину ключа (обычно API ключи имеют определенную длину)
    logger.info(f"Длина API ключа: {len(api_key)} символов")
    # Показываем первые и последние 4 символа для отладки (без полного раскрытия)
    if api_key:
        logger.info(f"API ключ (первые 4 символа): {api_key[:4]}...{api_key[-4:] if len(api_key) > 8 else '***'}")
    
    ocs_api = OCSAPI(api_key=api_key)
else:
    logger.error("API ключ не найден в переменных окружения!")
    ocs_api = None

@app.route('/')
def home():
    env_vars = {k: 'установлено' if v else 'не установлено' 
                for k, v in os.environ.items() if 'API' in k or 'KEY' in k}
    
    return jsonify({
        "status": "success", 
        "message": "OCS API работает на Render.com!",
        "api_key_configured": bool(api_key),
        "api_key_length": len(api_key) if api_key else 0,
        "environment_variables": env_vars,
        "python_version": sys.version,
        "cors_enabled": True
    })

@app.route('/api/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/debug')
def debug_info():
    """Эндпоинт для отладки"""
    return jsonify({
        "api_key_exists": bool(api_key),
        "api_key_prefix": api_key[:4] if api_key else None,
        "ocs_api_initialized": ocs_api is not None,
        "environment": dict(os.environ) if os.getenv('DEBUG_MODE') else "скрыто",
        "current_working_directory": os.getcwd(),
        "files_in_directory": os.listdir('.')
    })

@app.route('/api/test')
def test_api():
    if not ocs_api:
        logger.error("API ключ не настроен для тестового запроса")
        return jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "api_key_in_env": bool(os.getenv('OCS_API_KEY'))
        }), 500
    
    logger.info("Выполнение тестового запроса к OCS API")
    cities = ocs_api.get_shipment_cities()
    
    return jsonify({
        "success": True,
        "message": "API работает",
        "api_key_configured": True,
        "ocs_api_connection": "success" if cities else "failed",
        "available_cities": cities or [],
        "test_completed_at": datetime.datetime.now().isoformat()
    })

@app.route('/api/categories')
def get_categories():
    logger.info(f"Запрос категорий от клиента: {request.remote_addr}")
    
    if not ocs_api:
        logger.error("API ключ не настроен при запросе категорий")
        return jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "debug_info": {
                "env_var_exists": 'OCS_API_KEY' in os.environ,
                "api_key_length": len(api_key) if api_key else 0
            }
        }), 500
    
    logger.info("Отправка запроса категорий в OCS API")
    categories = ocs_api.get_categories()
    logger.info(f"Получено категорий: {len(categories) if categories else 0}")
    
    return jsonify({
        "success": True if categories else False,
        "data": categories or [],
        "source": "ocs_api",
        "request_time": datetime.datetime.now().isoformat(),
        "debug": {
            "api_called": True,
            "response_received": categories is not None
        }
    })

@app.route('/api/cities')
def get_cities():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    cities = ocs_api.get_shipment_cities()
    
    return jsonify({
        "success": True if cities else False,
        "data": cities or [],
        "debug": {
            "response_type": type(cities).__name__ if cities else "None"
        }
    })

@app.route('/api/products/category')
def get_products_by_category():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
        
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')

    # Логируем параметры для отладки
    logger.info(f"Products request - category: '{category}', city: '{shipment_city}'")
    logger.info(f"All query params: {dict(request.args)}")

    if category in ['undefined', 'null', '']:
        category = 'all'

    products = ocs_api.get_products_by_category(
        categories=category,
        shipment_city=shipment_city
    )
    
    logger.info(f"Products response type: {type(products)}")
    if products and 'result' in products:
        logger.info(f"Products count in result: {len(products.get('result', []))}")
    
    return jsonify({
        "success": True if products else False,
        "data": products or {"result": []},
        "total_count": len(products.get('result', [])) if products else 0,
        "source": "ocs_api",
        "debug_params": {
            "received_category": category,
            "received_city": shipment_city
        }
    })

@app.route('/api/products/search')
def search_products():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    if not search_term:
        return jsonify({"success": False, "error": "Не указан поисковый запрос"}), 400
    
    products = ocs_api.search_products(
        search_term=search_term,
        shipment_city=shipment_city
    )
    
    return jsonify({
        "success": True if products else False,
        "data": products or {"result": []},
        "search_term": search_term,
        "total_count": len(products.get('result', [])) if products else 0,
        "source": "ocs_api"
    })

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Необработанное исключение: {e}")
    return jsonify({
        "success": False,
        "error": str(e),
        "type": type(e).__name__
    }), 500

if __name__ == '__main__':
    import datetime
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Запуск приложения на порту {port}")
    logger.info(f"Текущее рабочее окружение: {os.environ.get('RENDER', 'Локально')}")
    app.run(host='0.0.0.0', port=port, debug=False)