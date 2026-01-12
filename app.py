import os
import requests
import logging
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import functools

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Простой кэш в памяти
cache = {}

def cache_response(ttl_seconds=300):
    """Декоратор для кэширования ответов"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Проверяем кэш
            if cache_key in cache:
                cached_data, timestamp = cache[cache_key]
                if datetime.now() - timestamp < timedelta(seconds=ttl_seconds):
                    logger.info(f"Cache hit for {cache_key}")
                    return cached_data
            
            # Выполняем функцию
            result = func(*args, **kwargs)
            
            # Сохраняем в кэш
            cache[cache_key] = (result, datetime.now())
            logger.info(f"Cached response for {cache_key}")
            
            return result
        return wrapper
    return decorator

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    response = make_response('', 200)
    response.headers.add('Content-Type', 'application/json')
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
        # Настройки сессии
        self.session.mount('https://', requests.adapters.HTTPAdapter(
            max_retries=3,
            pool_connections=10,
            pool_maxsize=10
        ))
    
    def _make_request(self, endpoint: str, params=None, method='GET', data=None):
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"OCS API: {url}")
            
            # Оптимизированные таймауты
            timeout_config = (360, 360)  # 70 секунд на соединение, 120 на чтение
            
            start_time = time.time()
            
            if method == 'GET':
                response = self.session.get(url, params=params, timeout=timeout_config, verify=True)
            elif method == 'POST':
                response = self.session.post(url, params=params, json=data, timeout=timeout_config, verify=True)
            elif method == 'PUT':
                response = self.session.put(url, params=params, json=data, timeout=timeout_config, verify=True)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params, timeout=timeout_config, verify=True)
            else:
                logger.error(f"Unsupported method: {method}")
                return None
            
            elapsed = time.time() - start_time
            logger.info(f"OCS API response time: {elapsed:.2f}s for {url}")
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"OCS API Error {response.status_code}: {response.text[:500]}")
                return {"error": f"OCS API returned {response.status_code}"}
                
        except requests.exceptions.Timeout:
            logger.error(f"OCS API Timeout: {url}")
            return {"error": "Timeout connecting to OCS API"}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"OCS API Connection Error: {url} - {str(e)}")
            return {"error": f"Connection error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"OCS API Request Exception: {url} - {str(e)}")
            return {"error": f"Request exception: {str(e)}"}
        except Exception as e:
            logger.error(f"OCS API Exception: {e}")
            return {"error": str(e)}

    @cache_response(ttl_seconds=600)  # Кэшируем на 10 минут
    def get_categories(self):
        """Получение категорий с кэшированием"""
        return self._make_request("catalog/categories")
    
    @cache_response(ttl_seconds=600)
    def get_shipment_cities(self):
        """Получение городов с кэшированием"""
        return self._make_request("logistic/shipment/cities")
    
    def get_products_by_category(self, categories: str, shipmentcity: str, **params):
        endpoint = f"catalog/categories/{categories}/products"
        params['shipmentcity'] = shipmentcity
        params['limit'] = params.get('limit', 50)
        return self._make_request(endpoint, params=params)
    
    def search_products(self, search_term: str, shipmentcity: str, **params):
        endpoint = f"catalog/categories/all/products"
        params['shipmentcity'] = shipmentcity
        params['search'] = search_term
        params['limit'] = params.get('limit', 50)
        return self._make_request(endpoint, params=params)

# Инициализация API
api_key = os.getenv('OCS_API_KEY')
if not api_key:
    logger.warning("OCS_API_KEY not found in environment variables")
    ocs_api = None
else:
    logger.info(f"API key loaded, length: {len(api_key)}")
    ocs_api = OCSAPI(api_key=api_key)

@app.route('/')
def home():
    response = jsonify({
        "status": "success", 
        "message": "OCS B2B API Proxy Service v2",
        "version": "2.0.0",
        "api_key_configured": bool(api_key),
        "cors_enabled": True,
        "cache_enabled": True,
        "timestamp": datetime.now().isoformat(),
        "endpoints": [
            "/api/v2/health",
            "/api/v2/test",
            "/api/v2/catalog/categories",
            "/api/v2/logistic/shipment/cities"
        ]
    })
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/health')
def health_check():
    response = jsonify({
        "status": "healthy",
        "service": "OCS API Proxy",
        "cache_size": len(cache),
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/test')
def test_api():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    # Тестируем оба эндпоинта
    cities_result = ocs_api.get_shipment_cities()
    categories_result = ocs_api.get_categories()
    
    cities_success = cities_result and "error" not in cities_result
    categories_success = categories_result and "error" not in categories_result
    
    response = jsonify({
        "success": cities_success and categories_success,
        "api_key_configured": True,
        "endpoints": {
            "cities": {
                "success": cities_success,
                "error": cities_result.get("error") if not cities_success else None,
                "has_data": bool(cities_result and isinstance(cities_result, list))
            },
            "categories": {
                "success": categories_success,
                "error": categories_result.get("error") if not categories_success else None,
                "has_data": bool(categories_result and isinstance(categories_result, list))
            }
        },
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/categories')
def get_categories():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        categories = ocs_api.get_categories()
        
        if categories and "error" in categories:
            response = jsonify({
                "success": False,
                "error": categories.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True,
                "data": categories or [],
                "cached": categories is not None and "error" not in categories,
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_categories: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/logistic/shipment/cities')
def get_cities():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        cities = ocs_api.get_shipment_cities()
        
        if cities and "error" in cities:
            response = jsonify({
                "success": False,
                "error": cities.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True,
                "data": cities or [],
                "cached": cities is not None and "error" not in cities,
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_cities: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/categories/<path:category>/products')
def get_products_by_category(category):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    shipmentcity = request.args.get('shipmentcity', 'Красноярск')
    
    if category in ['undefined', 'null', '']:
        category = 'all'
    
    try:
        products = ocs_api.get_products_by_category(
            categories=category,
            shipmentcity=shipmentcity,
            **request.args.to_dict()
        )
        
        if products and "error" in products:
            response = jsonify({
                "success": False,
                "error": products.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if products else False,
                "data": products or {"result": []},
                "total_count": len(products.get('result', [])) if products else 0,
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_products_by_category: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/categories/all/products')
def search_products():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    search_term = request.args.get('q', '')
    shipmentcity = request.args.get('shipmentcity', 'Красноярск')
    
    if not search_term:
        response = jsonify({
            "success": False,
            "error": "Не указан поисковый запрос",
            "message": "Используйте параметр q для поиска"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 400
    
    try:
        products = ocs_api.search_products(
            search_term=search_term,
            shipmentcity=shipmentcity,
            **request.args.to_dict()
        )
        
        if products and "error" in products:
            response = jsonify({
                "success": False,
                "error": products.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if products else False,
                "data": products or {"result": []},
                "search_term": search_term,
                "total_count": len(products.get('result', [])) if products else 0,
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in search_products: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/debug/cache')
def debug_cache():
    """Эндпоинт для отладки кэша"""
    cache_info = []
    for key, (value, timestamp) in cache.items():
        age = datetime.now() - timestamp
        cache_info.append({
            "key": key,
            "age_seconds": age.total_seconds(),
            "has_error": isinstance(value, dict) and "error" in value
        })
    
    response = jsonify({
        "cache_size": len(cache),
        "cache_entries": cache_info,
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/debug/clear-cache')
def clear_cache():
    """Очистка кэша"""
    global cache
    old_size = len(cache)
    cache.clear()
    
    response = jsonify({
        "success": True,
        "message": "Cache cleared",
        "cleared_entries": old_size,
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)