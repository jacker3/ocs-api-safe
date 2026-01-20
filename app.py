import os
import requests
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from datetime import datetime, timedelta
import time

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Конфигурация
API_KEY = os.getenv('OCS_API_KEY')
BASE_URL = 'https://connector.b2b.ocs.ru/api/v2'

# Кэш с автоматическим удалением старых записей
cache = {}
CACHE_TIMEOUT = 300  # 5 минут

class OCSClient:
    def __init__(self):
        self.session = requests.Session()
        if API_KEY:
            self.session.headers.update({
                'accept': 'application/json',
                'X-API-Key': API_KEY,
                'User-Agent': 'OCS-API/1.0'
            })
        # Очищаем старый кэш при инициализации
        self._clean_old_cache()
    
    def _clean_old_cache(self):
        """Очистка устаревшего кэша"""
        now = datetime.now().timestamp()
        keys_to_delete = []
        for key, (_, timestamp) in cache.items():
            if now - timestamp > CACHE_TIMEOUT:
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del cache[key]
    
    def _make_request(self, method, endpoint, params=None, data=None, 
                     use_cache=True, timeout=(3, 15)):
        """Универсальный метод для выполнения запросов"""
        if not API_KEY:
            return {'error': 'API key not configured'}
        
        # Создаем ключ кэша
        cache_key = f"{method}:{endpoint}:{json.dumps(params, sort_keys=True) if params else 'none'}"
        
        # Проверка кэша
        if use_cache and cache_key in cache:
            cached_data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TIMEOUT:
                logger.info(f"Cache hit for {endpoint}")
                return cached_data
        
        try:
            url = f"{BASE_URL}{endpoint}"
            logger.info(f"Making request to: {url}")
            
            start_time = time.time()
            
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=data,
                timeout=timeout
            )
            
            elapsed = time.time() - start_time
            logger.info(f"Request completed in {elapsed:.2f}s, status: {response.status_code}")
            
            if response.status_code != 200:
                error_msg = response.text[:200] if response.text else 'No error message'
                logger.error(f"Error {response.status_code}: {error_msg}")
                result = {
                    'error': f'HTTP {response.status_code}',
                    'message': error_msg
                }
                return result
            
            result = response.json()
            
            # Кэшируем успешные ответы
            if use_cache and response.status_code == 200:
                cache[cache_key] = (result, datetime.now().timestamp())
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout for {endpoint}")
            return {'error': 'Request timeout', 'suggestion': 'Try with smaller dataset or specific categories'}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return {'error': 'Connection failed', 'details': str(e)}
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {'error': str(e)}
    
    # ============ КАТАЛОГ ============
    
    def get_categories(self):
        """Дерево категорий - используем кэш и короткий таймаут"""
        return self._make_request('GET', '/catalog/categories', use_cache=True, timeout=(3, 10))
    
    def get_products_by_category(self, category, shipmentcity, **params):
        """Товары по КОНКРЕТНОЙ категории"""
        endpoint = f"/catalog/categories/{category}/products"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        # Для конкретной категории используем нормальный таймаут
        return self._make_request('GET', endpoint, params=query_params, use_cache=True, timeout=(5, 20))
    
    def get_products_by_categories_batch(self, categories, shipmentcity, **params):
        """Товары по нескольким категориям (batch) - ограничиваем количество!"""
        if len(categories) > 10:  # Ограничиваем количество категорий
            return {'error': 'Too many categories', 'max_allowed': 10}
        
        endpoint = "/catalog/categories/batch/products"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        data = categories
        # Batch запросы могут быть долгими
        return self._make_request('POST', endpoint, params=query_params, data=data, use_cache=False, timeout=(5, 30))
    
    def get_product_info(self, item_id, shipmentcity, **params):
        """Информация по конкретному товару"""
        endpoint = f"/catalog/products/{item_id}"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        return self._make_request('GET', endpoint, params=query_params, use_cache=True, timeout=(3, 10))
    
    def get_products_info_batch(self, item_ids, shipmentcity, **params):
        """Информация по нескольким товарам (batch) - ограничиваем количество!"""
        if len(item_ids) > 50:  # Ограничиваем количество товаров
            return {'error': 'Too many items', 'max_allowed': 50}
        
        endpoint = "/catalog/products/batch"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        data = item_ids
        return self._make_request('POST', endpoint, params=query_params, data=data, use_cache=False, timeout=(5, 20))
    
    def get_certificates(self, item_id, actuality='actual'):
        """Сертификаты"""
        endpoint = f"/catalog/products/{item_id}/certificates"
        params = {'actuality': actuality}
        return self._make_request('GET', endpoint, params=params, use_cache=True, timeout=(3, 10))
    
    # ============ ЛОГИСТИКА ============
    
    def get_shipment_cities(self):
        """Города отгрузки"""
        return self._make_request('GET', '/logistic/shipment/cities', use_cache=True, timeout=(3, 5))
    
    def get_stock_locations(self, shipmentcity):
        """Местоположения товаров"""
        endpoint = "/logistic/stocks/locations"
        params = {'shipmentcity': shipmentcity}
        return self._make_request('GET', endpoint, params=params, use_cache=True, timeout=(3, 10))
    
    # ============ АККАУНТ ============
    
    def get_currency_exchanges(self):
        """Курсы валют"""
        return self._make_request('GET', '/account/currencies/exchanges', use_cache=False, timeout=(3, 10))
    
    def get_payers(self):
        """Плательщики"""
        return self._make_request('GET', '/account/payers', use_cache=True, timeout=(3, 10))

client = OCSClient()

# ============ РУЧКИ API ============

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS API Proxy',
        'status': 'operational',
        'endpoints': {
            'cities': '/api/cities',
            'categories': '/api/categories',
            'products_by_category': '/api/categories/<category>/products?shipmentcity=...',
            'product_info': '/api/products/<item_id>?shipmentcity=...',
            'currency': '/api/currency',
            'payers': '/api/payers'
        },
        'recommendations': [
            'Используйте конкретные категории вместо "all"',
            'Ограничивайте количество товаров в batch запросах',
            'Кэширование включено для часто запрашиваемых данных'
        ]
    })

@app.route('/api/cities')
def get_cities():
    """Города отгрузки"""
    result = client.get_shipment_cities()
    return jsonify(result)

@app.route('/api/categories')
def get_categories():
    """Дерево категорий"""
    result = client.get_categories()
    return jsonify(result)

@app.route('/api/categories/<category>/products')
def get_category_products(category):
    """Товары по категории"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    # Безопасные параметры по умолчанию
    params = {
        'onlyavailable': 'true',
        'includeregular': 'true',
        'includesale': 'false',
        'includeuncondition': 'false',
        'includemissing': 'false',
        'withdescriptions': 'true'  # Можем отключить для ускорения
    }
    
    # Переопределяем параметры из запроса
    for param in ['onlyavailable', 'includeregular', 'includesale', 
                  'includeuncondition', 'includemissing', 'withdescriptions',
                  'locations', 'producers']:
        if param in request.args:
            params[param] = request.args.get(param)
    
    # ВАЖНО: Предупреждение для запроса 'all'
    if category.lower() == 'all':
        return jsonify({
            'warning': 'Requesting ALL categories may timeout',
            'suggestion': 'Use specific category codes instead',
            'example_categories': ['V01', 'V0100', 'V0101'],
            'endpoint': '/api/categories/batch/products for multiple categories'
        })
    
    result = client.get_products_by_category(category, shipmentcity, **params)
    return jsonify(result)

@app.route('/api/categories/batch/products', methods=['POST'])
def get_categories_products_batch():
    """Товары по нескольким категориям (ограничено 10 категорий)"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({'error': 'JSON array of categories required'}), 400
        
        if len(data) > 10:
            return jsonify({'error': 'Maximum 10 categories allowed', 'received': len(data)}), 400
        
        params = {
            'onlyavailable': request.args.get('onlyavailable', 'true'),
            'includeregular': request.args.get('includeregular', 'true'),
            'withdescriptions': request.args.get('withdescriptions', 'true')
        }
        
        result = client.get_products_by_categories_batch(data, shipmentcity, **params)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/products/<item_id>')
def get_product_info(item_id):
    """Информация по товару"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    params = {
        'includeregular': request.args.get('includeregular', 'true'),
        'withdescriptions': request.args.get('withdescriptions', 'true')
    }
    
    result = client.get_product_info(item_id, shipmentcity, **params)
    return jsonify(result)

@app.route('/api/products/batch', methods=['POST'])
def get_products_info_batch():
    """Информация по нескольким товарам (ограничено 50 товаров)"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({'error': 'JSON array of item IDs required'}), 400
        
        if len(data) > 50:
            return jsonify({'error': 'Maximum 50 items allowed', 'received': len(data)}), 400
        
        params = {
            'includeregular': request.args.get('includeregular', 'true'),
            'withdescriptions': request.args.get('withdescriptions', 'true')
        }
        
        result = client.get_products_info_batch(data, shipmentcity, **params)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/currency')
def get_currency():
    """Курсы валют"""
    result = client.get_currency_exchanges()
    return jsonify(result)

@app.route('/api/payers')
def get_payers():
    """Плательщики"""
    result = client.get_payers()
    return jsonify(result)

@app.route('/api/certificates/<item_id>')
def get_certificates(item_id):
    """Сертификаты на товар"""
    actuality = request.args.get('actuality', 'actual')
    result = client.get_certificates(item_id, actuality)
    return jsonify(result)

@app.route('/api/locations')
def get_locations():
    """Местоположения товаров"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    result = client.get_stock_locations(shipmentcity)
    return jsonify(result)

# ============ СЕРВИСНЫЕ РУЧКИ ============

@app.route('/api/health')
def health():
    """Health check"""
    # Проверяем базовые методы без тяжелых запросов
    cities_test = client.get_shipment_cities()
    
    return jsonify({
        'status': 'ok' if 'error' not in cities_test else 'degraded',
        'timestamp': datetime.now().isoformat(),
        'basic_api': 'ok' if 'error' not in cities_test else 'failed',
        'cache_size': len(cache),
        'recommendation': 'Use specific categories instead of "all" for product queries'
    })

@app.route('/api/debug')
def debug():
    """Отладочная информация"""
    # Быстрая проверка без тяжелых запросов
    cities = client.get_shipment_cities()
    currency = client.get_currency_exchanges()
    
    return jsonify({
        'api_key_configured': bool(API_KEY),
        'base_url': BASE_URL,
        'simple_requests': {
            'cities': 'ok' if 'error' not in cities else 'failed',
            'currency': 'ok' if 'error' not in currency else 'failed'
        },
        'cache': {
            'entries': len(cache),
            'keys': list(cache.keys())[:3]
        },
        'common_issues': [
            'Timeout on /categories/all/products - request is too large',
            'Use specific category codes like V01, V0100 instead of "all"',
            'Limit batch requests to 10 categories or 50 items'
        ]
    })

@app.route('/api/examples')
def examples():
    """Примеры рабочих запросов"""
    # Сначала получаем список городов из кэша или делаем запрос
    cities_result = client.get_shipment_cities()
    example_city = 'Краснодар'  # Дефолтный город
    
    if 'error' not in cities_result and isinstance(cities_result, list) and len(cities_result) > 0:
        example_city = cities_result[0]
    elif isinstance(cities_result, dict) and 'error' not in cities_result.get('result', []):
        result = cities_result.get('result', [])
        if result and isinstance(result, list) and len(result) > 0:
            example_city = result[0]
    
    return jsonify({
        'working_examples': [
            f'GET /api/cities',
            f'GET /api/currency',
            f'GET /api/payers',
            f'GET /api/categories',
            f'GET /api/categories/V01/products?shipmentcity={example_city}&onlyavailable=true',
            f'GET /api/products/1000459749?shipmentcity={example_city}',
            f'GET /api/certificates/1000459619',
            f'GET /api/locations?shipmentcity={example_city}'
        ],
        'batch_examples': [
            'POST /api/categories/batch/products?shipmentcity=... with JSON: ["V01", "V0100"]',
            'POST /api/products/batch?shipmentcity=... with JSON: ["1000459749", "1000459646"]'
        ],
        'tips': [
            'Always include shipmentcity parameter',
            'Start with small requests before requesting large datasets',
            'Use cache-friendly endpoints for repeated queries'
        ]
    })

@app.route('/api/cache/clear')
def clear_cache():
    """Очистка кэша"""
    cache.clear()
    return jsonify({'message': 'Cache cleared', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        threaded=True
    )