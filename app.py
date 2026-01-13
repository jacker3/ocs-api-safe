import os
import requests
import logging
import time
import json
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import functools
import queue

load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    return make_response('', 200)

class OCSAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = os.getenv('OCS_API_URL', 'https://connector.b2b.ocs.ru/api/v2')
        self.session = requests.Session()
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': 'OCS-Integration/1.0'
        })
        
        # Увеличиваем таймауты сессии
        self.session.mount('https://', requests.adapters.HTTPAdapter(
            max_retries=3,
            pool_connections=10,
            pool_maxsize=10
        ))
        
        logger.info(f"OCS API initialized with URL: {self.base_url}")
    
    def _make_request(self, endpoint: str, params=None, method='GET', data=None, custom_timeout=None):
        """Базовый метод для выполнения запросов к OCS API с логированием"""
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"OCS API Request: {method} {url}")
            
            # Настройка таймаутов в зависимости от типа запроса
            if custom_timeout:
                timeout = custom_timeout
            elif 'catalog/categories' in endpoint:
                # Для категорий - самый большой таймаут
                timeout = (120, 300)  # 120 сек на соединение, 300 на чтение
            elif 'catalog' in endpoint:
                # Для каталога товаров
                timeout = (60, 180)  # 60 сек на соединение, 180 на чтение
            else:
                # Для остальных запросов
                timeout = (30, 120)  # 30 сек на соединение, 120 на чтение
            
            start_time = time.time()
            
            # Выполняем запрос
            if method == 'GET':
                response = self.session.get(url, params=params, timeout=timeout, verify=True)
            elif method == 'POST':
                response = self.session.post(url, params=params, json=data, timeout=timeout, verify=True)
            elif method == 'PUT':
                response = self.session.put(url, params=params, json=data, timeout=timeout, verify=True)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params, timeout=timeout, verify=True)
            else:
                logger.error(f"Unsupported method: {method}")
                return {"error": f"Unsupported method: {method}", "code": 400}
            
            elapsed = time.time() - start_time
            logger.info(f"OCS API Response: {method} {url} - Status: {response.status_code}, Time: {elapsed:.2f}s")
            
            # Обработка ответа
            if response.status_code == 200:
                try:
                    return response.json()
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    return {"error": "Invalid JSON response", "text": response.text[:200], "code": 500}
            elif response.status_code == 429:
                logger.warning("Rate limit exceeded")
                return {"error": "Rate limit exceeded", "code": 429}
            elif response.status_code >= 400:
                error_msg = f"HTTP error {response.status_code}"
                logger.error(f"{error_msg}: {response.text[:200]}")
                return {"error": error_msg, "code": response.status_code}
            else:
                return {"error": f"Unexpected status code: {response.status_code}", "code": response.status_code}
                
        except requests.exceptions.Timeout:
            logger.error(f"Timeout for {method} {endpoint}")
            return {"error": "Request timeout", "code": 408}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return {"error": f"Connection error: {str(e)}", "code": 503}
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {"error": str(e), "code": 500}

    # ===== ОСНОВНЫЕ МЕТОДЫ =====
    
    @cache_response(ttl_seconds=1800)  # 30 минут
    def get_categories(self):
        """Получение категорий товаров"""
        return self._make_request("catalog/categories")
    
    @cache_response(ttl_seconds=1800)  # 30 минут
    def get_shipment_cities(self):
        """Получение городов отгрузки"""
        return self._make_request("logistic/shipment/cities")
    
    def get_products_by_category(self, category: str, shipment_city: str, **params):
        """Получение товаров по категории"""
        endpoint = f"catalog/categories/{category}/products"
        all_params = {'shipmentcity': shipment_city}
        all_params.update(params)
        return self._make_request(endpoint, params=all_params)
    
    def get_products_by_ids(self, item_ids: str, shipment_city: str, **params):
        """Получение товаров по ID"""
        endpoint = f"catalog/products/{item_ids}"
        all_params = {'shipmentcity': shipment_city}
        all_params.update(params)
        return self._make_request(endpoint, params=all_params)
    
    def get_products_by_ids_batch(self, item_ids_list: list, shipment_city: str, **params):
        """Batch-запрос товаров"""
        endpoint = "catalog/products/batch"
        all_params = {'shipmentcity': shipment_city}
        all_params.update(params)
        return self._make_request(endpoint, method='POST', data=item_ids_list, params=all_params)

# Инициализация API
api_key = os.getenv('OCS_API_KEY')
if not api_key:
    logger.warning("OCS_API_KEY not found in environment variables")
    ocs_api = None
else:
    logger.info("OCS API initialized successfully")
    ocs_api = OCSAPI(api_key=api_key)

# ===== ПРОСТЫЕ И НАДЕЖНЫЕ ЭНДПОИНТЫ =====

@app.route('/')
def home():
    """Главная страница"""
    return jsonify({
        "service": "OCS B2B API Proxy",
        "version": "2.0.0",
        "status": "operational" if ocs_api else "no_api_key",
        "endpoints": {
            "health": "/api/v2/health",
            "test": "/api/v2/test",
            "cities": "/api/v2/logistic/shipment/cities",
            "categories": "/api/v2/catalog/categories",
            "products_by_category": "/api/v2/catalog/categories/{category}/products",
            "products_by_ids": "/api/v2/catalog/products/{item_ids}"
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/health')
def health_check():
    """Проверка здоровья сервиса"""
    return jsonify({
        "status": "healthy",
        "ocs_api_configured": bool(ocs_api),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/test')
def test_api():
    """Тестовый запрос к OCS API"""
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    # Тестируем только быстрый эндпоинт
    result = ocs_api.get_shipment_cities()
    
    if result and "error" not in result:
        return jsonify({
            "success": True,
            "data": result[:5] if isinstance(result, list) else result,  # Только первые 5 элементов
            "total_count": len(result) if isinstance(result, list) else 1,
            "timestamp": datetime.now().isoformat()
        })
    else:
        return jsonify({
            "success": False,
            "error": result.get("error", "Unknown error") if result else "No response",
            "code": result.get("code", 500) if result else 500,
            "timestamp": datetime.now().isoformat()
        }), result.get("code", 500) if result else 500

@app.route('/api/v2/logistic/shipment/cities')
def get_cities():
    """Получение городов отгрузки"""
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    try:
        result = ocs_api.get_shipment_cities()
        
        if result and "error" not in result:
            return jsonify({
                "success": True,
                "data": result,
                "cached": True,
                "timestamp": datetime.now().isoformat()
            })
        else:
            error_msg = result.get("error", "Unknown error") if result else "No response"
            error_code = result.get("code", 500) if result else 500
            return jsonify({
                "success": False,
                "error": error_msg,
                "code": error_code,
                "timestamp": datetime.now().isoformat()
            }), error_code
            
    except Exception as e:
        logger.error(f"Error in get_cities: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/v2/catalog/categories')
def get_categories_endpoint():
    """Получение категорий товаров (с обработкой таймаутов)"""
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    # Параметр для ограничения глубины (если API медленный)
    limit_depth = request.args.get('limit_depth', 'false').lower() == 'true'
    
    try:
        logger.info(f"Fetching categories, limit_depth: {limit_depth}")
        
        # Даем больше времени на первый запрос
        result = ocs_api.get_categories()
        
        if result and "error" not in result:
            # Если запросили ограничение глубины, можно упростить структуру
            if limit_depth and isinstance(result, list):
                # Ограничиваем вложенность для отладки
                simplified = []
                for item in result[:10]:  # Только первые 10 категорий для отладки
                    if isinstance(item, dict):
                        simplified_item = {
                            'category': item.get('category'),
                            'name': item.get('name'),
                            'has_children': bool(item.get('children'))
                        }
                        simplified.append(simplified_item)
                result = simplified
            
            return jsonify({
                "success": True,
                "data": result,
                "cached": True,
                "total_count": len(result) if isinstance(result, list) else 0,
                "timestamp": datetime.now().isoformat(),
                "note": "This endpoint may be slow due to large data from OCS"
            })
        else:
            error_msg = result.get("error", "Unknown error") if result else "No response"
            error_code = result.get("code", 500) if result else 500
            
            # Специальная обработка таймаутов
            if error_code == 408:
                return jsonify({
                    "success": False,
                    "error": "Request timeout - OCS API is slow to respond",
                    "suggestion": "Try again or contact support",
                    "code": 408,
                    "timestamp": datetime.now().isoformat()
                }), 408
            
            return jsonify({
                "success": False,
                "error": error_msg,
                "code": error_code,
                "timestamp": datetime.now().isoformat()
            }), error_code
            
    except Exception as e:
        logger.error(f"Error in get_categories: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "suggestion": "Try ?limit_depth=true for faster response",
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/v2/catalog/categories/<path:category>/products')
def get_products_by_category_endpoint(category):
    """Получение товаров по категории"""
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipmentcity', 'Москва')
    
    # Нормализация категории
    if category in ['all', 'undefined', 'null', '']:
        category = 'all'
    
    try:
        # Собираем параметры
        params = request.args.to_dict()
        if 'shipmentcity' in params:
            shipment_city = params.pop('shipmentcity')
        
        logger.info(f"Fetching products for category: {category}, city: {shipment_city}")
        
        result = ocs_api.get_products_by_category(category, shipment_city, **params)
        
        if result and "error" not in result:
            products = result.get('result', [])
            return jsonify({
                "success": True,
                "data": result,
                "category": category,
                "shipment_city": shipment_city,
                "product_count": len(products),
                "timestamp": datetime.now().isoformat()
            })
        else:
            error_msg = result.get("error", "Unknown error") if result else "No response"
            error_code = result.get("code", 500) if result else 500
            return jsonify({
                "success": False,
                "error": error_msg,
                "code": error_code,
                "timestamp": datetime.now().isoformat()
            }), error_code
            
    except Exception as e:
        logger.error(f"Error in get_products_by_category: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/v2/catalog/products/<path:item_ids>')
def get_products_by_ids_endpoint(item_ids):
    """Получение товаров по ID"""
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipmentcity', 'Москва')
    
    try:
        # Собираем параметры
        params = request.args.to_dict()
        if 'shipmentcity' in params:
            shipment_city = params.pop('shipmentcity')
        
        # Ограничиваем количество ID для одного запроса
        ids_list = item_ids.split(',')
        if len(ids_list) > 50:
            return jsonify({
                "success": False,
                "error": "Too many IDs (max 50 per request)",
                "suggestion": "Use batch endpoint for more IDs",
                "batch_endpoint": "/api/v2/catalog/products/batch",
                "timestamp": datetime.now().isoformat()
            }), 400
        
        logger.info(f"Fetching {len(ids_list)} products, city: {shipment_city}")
        
        result = ocs_api.get_products_by_ids(item_ids, shipment_city, **params)
        
        if result and "error" not in result:
            products = result.get('result', [])
            return jsonify({
                "success": True,
                "data": result,
                "shipment_city": shipment_city,
                "product_count": len(products),
                "timestamp": datetime.now().isoformat()
            })
        else:
            error_msg = result.get("error", "Unknown error") if result else "No response"
            error_code = result.get("code", 500) if result else 500
            return jsonify({
                "success": False,
                "error": error_msg,
                "code": error_code,
                "timestamp": datetime.now().isoformat()
            }), error_code
            
    except Exception as e:
        logger.error(f"Error in get_products_by_ids: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/v2/catalog/products/batch', methods=['POST'])
def get_products_batch_endpoint():
    """Batch-запрос товаров"""
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        item_ids = data.get('items', [])
        shipment_city = data.get('shipmentcity', 'Москва')
        params = data.get('params', {})
        
        if not item_ids:
            return jsonify({"success": False, "error": "No items provided"}), 400
        
        # Ограничиваем размер батча
        if len(item_ids) > 100:
            return jsonify({
                "success": False,
                "error": "Batch too large (max 100 items)",
                "received": len(item_ids),
                "timestamp": datetime.now().isoformat()
            }), 400
        
        logger.info(f"Batch request for {len(item_ids)} products, city: {shipment_city}")
        
        result = ocs_api.get_products_by_ids_batch(item_ids, shipment_city, **params)
        
        if result and "error" not in result:
            products = result.get('result', [])
            return jsonify({
                "success": True,
                "data": result,
                "batch_size": len(item_ids),
                "product_count": len(products),
                "timestamp": datetime.now().isoformat()
            })
        else:
            error_msg = result.get("error", "Unknown error") if result else "No response"
            error_code = result.get("code", 500) if result else 500
            return jsonify({
                "success": False,
                "error": error_msg,
                "code": error_code,
                "timestamp": datetime.now().isoformat()
            }), error_code
            
    except Exception as e:
        logger.error(f"Error in batch endpoint: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

# ===== УТИЛИТЫ И ОТЛАДКА =====

@app.route('/api/v2/debug/cache')
def debug_cache():
    """Отладка кэша"""
    cache_info = []
    for key, (value, timestamp) in cache.items():
        age = datetime.now() - timestamp
        cache_info.append({
            "key": key[:100] + "..." if len(key) > 100 else key,
            "age_seconds": int(age.total_seconds()),
            "age_human": str(age).split('.')[0],
            "type": type(value).__name__
        })
    
    return jsonify({
        "cache_size": len(cache),
        "cache_entries": cache_info,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/debug/clear-cache')
def clear_cache_endpoint():
    """Очистка кэша"""
    global cache
    old_size = len(cache)
    cache.clear()
    
    return jsonify({
        "success": True,
        "message": "Cache cleared",
        "cleared_entries": old_size,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/debug/status')
def debug_status():
    """Статус сервиса"""
    return jsonify({
        "service": "OCS API Proxy",
        "status": "running",
        "ocs_api": {
            "configured": bool(ocs_api),
            "base_url": ocs_api.base_url if ocs_api else None,
            "api_key_length": len(api_key) if api_key else 0
        },
        "cache": {
            "size": len(cache),
            "keys": [k[:50] + "..." if len(k) > 50 else k for k in list(cache.keys())[:3]]
        },
        "timestamp": datetime.now().isoformat(),
        "environment": {
            "flask_env": os.environ.get('FLASK_ENV', 'production'),
            "port": os.environ.get('PORT', 10000)
        }
    })

@app.route('/api/v2/debug/test-slow')
def test_slow_endpoint():
    """Тестовый эндпоинт для проверки таймаутов"""
    delay = int(request.args.get('delay', 10))
    
    logger.info(f"Test slow endpoint with delay: {delay}s")
    
    if delay > 30:
        return jsonify({
            "success": False,
            "error": "Delay too long (max 30s)",
            "timestamp": datetime.now().isoformat()
        }), 400
    
    time.sleep(delay)
    
    return jsonify({
        "success": True,
        "message": f"Delayed response after {delay} seconds",
        "timestamp": datetime.now().isoformat()
    })

# ===== ОБРАБОТКА ОШИБОК =====

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Not found",
        "message": str(error),
        "timestamp": datetime.now().isoformat()
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({
        "success": False,
        "error": "Internal server error",
        "message": "An unexpected error occurred",
        "timestamp": datetime.now().isoformat()
    }), 500

# ===== ЗАПУСК СЕРВЕРА =====

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    logger.info(f"Starting OCS API Proxy on port {port}")
    logger.info(f"OCS API URL: {ocs_api.base_url if ocs_api else 'Not configured'}")
    logger.info(f"Cache size: {len(cache)}")
    
    # Запуск с увеличенными таймаутами для разработки
    if os.environ.get('FLASK_ENV') == 'development':
        logger.info("Running in development mode")
        app.run(host='0.0.0.0', port=port, debug=True, threaded=True)
    else:
        # Для production используем waitress или gunicorn
        logger.info("Running in production mode")
        from waitress import serve
        serve(app, host='0.0.0.0', port=port, threads=50)