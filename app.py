import os
import requests
import json
from flask import Flask, jsonify, request, abort
from flask_cors import CORS
import logging
from datetime import datetime
from urllib.parse import quote

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Конфигурация
API_KEY = os.getenv('OCS_API_KEY', os.getenv('OCS_API_KEY'))
BASE_URL = os.getenv('OCS_BASE_URL', 'https://connector.b2b.ocs.ru/api/v2')

# Кэш для ускорения повторных запросов
cache = {}
CACHE_TIMEOUT = 300  # 5 минут

class OCSClient:
    def __init__(self):
        self.session = requests.Session()
        if API_KEY:
            self.session.headers.update({
                'accept': 'application/json',
                'X-API-Key': API_KEY,
                'User-Agent': 'OCS-API-Render/1.0'
            })
        # Оптимальные таймауты для быстрого отклика
        self.connect_timeout = 3
        self.read_timeout = 10
    
    def _make_request(self, method, endpoint, params=None, data=None, use_cache=False):
        """Универсальный метод для выполнения запросов с кэшированием"""
        if not API_KEY:
            return {'error': 'API key not configured', 'result': None}
        
        cache_key = f"{method}:{endpoint}:{str(params)}:{str(data)}"
        
        # Проверка кэша
        if use_cache and cache_key in cache:
            cached_data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TIMEOUT:
                logger.info(f"Cache hit for {cache_key}")
                return cached_data
        
        try:
            url = f"{BASE_URL}{endpoint}"
            logger.info(f"Request: {method} {url}")
            
            if params:
                logger.debug(f"Params: {params}")
            
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=data,
                timeout=(self.connect_timeout, self.read_timeout)
            )
            
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Error response: {response.text[:500]}")
                result = {
                    'error': f'HTTP {response.status_code}',
                    'status_code': response.status_code,
                    'message': response.text[:500] if response.text else 'No message'
                }
                return result
            
            # Парсим JSON ответ
            try:
                result = response.json()
            except json.JSONDecodeError:
                result = {'raw_response': response.text}
            
            # Кэшируем успешный результат
            if use_cache and response.status_code == 200:
                cache[cache_key] = (result, datetime.now().timestamp())
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout for {endpoint}")
            return {'error': 'Request timeout', 'result': None}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return {'error': f'Connection failed: {str(e)}', 'result': None}
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {'error': str(e), 'result': None}
    
    def get_categories(self):
        """2.2.1 Получение информации о товарных категориях"""
        return self._make_request('GET', '/catalog/categories', use_cache=True)
    
    def get_categories_products(self, categories, shipmentcity, params=None):
        """
        2.2.2 Получение информации о состоянии склада и ценах по товарным категориям
        
        categories: 'all' или список категорий через запятую
        shipmentcity: город отгрузки (например, 'Москва')
        """
        endpoint = f"/catalog/categories/{categories}/products"
        
        # Базовые параметры
        query_params = {
            'shipmentcity': shipmentcity,
        }
        
        # Добавляем дополнительные параметры
        if params:
            query_params.update(params)
        
        return self._make_request('GET', endpoint, params=query_params, use_cache=False)
    
    def get_categories_products_batch(self, categories_list, shipmentcity, params=None):
        """
        2.2.3 Получение информации о состоянии склада и ценах по товарным категориям (batch)
        
        categories_list: список категорий ['V0100', 'V0101']
        """
        endpoint = "/catalog/categories/batch/products"
        
        # Базовые параметры
        query_params = {
            'shipmentcity': shipmentcity,
        }
        
        # Добавляем дополнительные параметры
        if params:
            query_params.update(params)
        
        # Данные в теле запроса
        data = categories_list
        
        return self._make_request('POST', endpoint, params=query_params, data=data, use_cache=False)
    
    def get_products_info(self, item_ids, shipmentcity, params=None):
        """
        2.2.4 Получение информации о состоянии склада и ценах по списку товаров
        
        item_ids: 'all' или список ID через запятую '1000459749,1000459646'
        """
        endpoint = f"/catalog/products/{item_ids}"
        
        # Базовые параметры
        query_params = {
            'shipmentcity': shipmentcity,
        }
        
        # Добавляем дополнительные параметры
        if params:
            query_params.update(params)
        
        return self._make_request('GET', endpoint, params=query_params, use_cache=False)
    
    def get_products_info_batch(self, item_ids_list, shipmentcity, params=None):
        """
        2.2.5 Получение информации о состоянии склада и ценах (batch)
        """
        endpoint = "/catalog/products/batch"
        
        # Базовые параметры
        query_params = {
            'shipmentcity': shipmentcity,
        }
        
        # Добавляем дополнительные параметры
        if params:
            query_params.update(params)
        
        data = item_ids_list
        
        return self._make_request('POST', endpoint, params=query_params, data=data, use_cache=False)
    
    def get_certificates(self, item_ids, actuality='actual'):
        """
        2.2.6 Получение информации о сертификатах на товарные позиции
        
        actuality: 'actual', 'expired', 'all'
        """
        endpoint = f"/catalog/products/{item_ids}/certificates"
        
        query_params = {
            'actuality': actuality
        }
        
        return self._make_request('GET', endpoint, params=query_params, use_cache=True)
    
    def get_certificates_batch(self, item_ids_list, actuality='actual'):
        """2.2.7 Получение информации о сертификатах (batch)"""
        endpoint = "/catalog/products/batch/certificates"
        
        query_params = {
            'actuality': actuality
        }
        
        data = item_ids_list
        
        return self._make_request('POST', endpoint, params=query_params, data=data, use_cache=False)
    
    def get_shipment_cities(self):
        """2.3.1/4.3.3 Получение информации о допустимых городах отгрузки"""
        return self._make_request('GET', '/logistic/shipment/cities', use_cache=True)
    
    def get_stock_locations(self, shipmentcity):
        """2.3.2 Получение информации о допустимых местоположениях товара"""
        endpoint = "/logistic/stocks/locations"
        
        query_params = {
            'shipmentcity': shipmentcity
        }
        
        return self._make_request('GET', endpoint, params=query_params, use_cache=True)
    
    def get_reserve_places(self, shipmentcity):
        """4.3.4 Получение информации о разрешенных местах резервирования"""
        endpoint = "/logistic/stocks/reserveplaces"
        
        query_params = {
            'shipmentcity': shipmentcity
        }
        
        return self._make_request('GET', endpoint, params=query_params, use_cache=True)
    
    def get_content(self, item_ids):
        """3.2.1 Получение характеристик товара"""
        endpoint = f"/content/{item_ids}"
        return self._make_request('GET', endpoint, use_cache=True)
    
    def get_content_batch(self, item_ids_list):
        """3.2.2 Получение характеристик товара (batch)"""
        endpoint = "/content/batch"
        data = item_ids_list
        return self._make_request('POST', endpoint, data=data, use_cache=False)
    
    def get_content_changes(self, from_date):
        """3.2.3 Получение списка товаров с изменениями в контенте"""
        endpoint = "/content/changes"
        
        query_params = {
            'from': from_date
        }
        
        return self._make_request('GET', endpoint, params=query_params, use_cache=False)
    
    def get_payers(self):
        """4.3.1 Получение информации о плательщиках"""
        return self._make_request('GET', '/account/payers', use_cache=True)
    
    def get_contact_persons(self):
        """4.3.2 Получение информации о контактных лицах"""
        return self._make_request('GET', '/account/contactpersons', use_cache=True)
    
    def get_currency_exchanges(self):
        """4.3.5 Получение курсов валют"""
        return self._make_request('GET', '/account/currencies/exchanges', use_cache=False)
    
    def get_finances(self):
        """7.3.3 Получение информации по кредитным средствам партнёра"""
        return self._make_request('GET', '/account/finances', use_cache=False)
    
    def get_consignees(self):
        """7.3.4 Получение информации о грузополучателях"""
        return self._make_request('GET', '/account/consignees', use_cache=True)
    
    def get_pickup_points(self, shipmentcity):
        """7.3.5 Получение информации о пунктах выдачи"""
        endpoint = "/logistic/shipment/pickup-points"
        
        query_params = {
            'shipmentcity': shipmentcity
        }
        
        return self._make_request('GET', endpoint, params=query_params, use_cache=True)
    
    def get_delivery_addresses(self, shipmentcity):
        """7.3.8 Получение списка зарегистрированных адресов доставки"""
        endpoint = "/logistic/shipment/delivery-addresses"
        
        query_params = {
            'shipmentcity': shipmentcity
        }
        
        return self._make_request('GET', endpoint, params=query_params, use_cache=True)

client = OCSClient()

# ================ РУЧКИ КАТАЛОГА ================

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS API Proxy',
        'version': '1.0',
        'status': 'active',
        'documentation': {
            'catalog': 'Получение информации о товарах и категориях',
            'logistic': 'Информация по логистике и городам',
            'orders': 'Работа с заказами (требует дополнительных прав)',
            'content': 'Контент товаров',
            'account': 'Справочная информация'
        },
        'endpoints': [
            {'method': 'GET', 'path': '/catalog/categories', 'desc': 'Дерево категорий'},
            {'method': 'GET', 'path': '/catalog/categories/<categories>/products?shipmentcity=...', 'desc': 'Товары по категориям'},
            {'method': 'POST', 'path': '/catalog/categories/batch/products?shipmentcity=...', 'desc': 'Товары по категориям (batch)'},
            {'method': 'GET', 'path': '/catalog/products/<item_ids>?shipmentcity=...', 'desc': 'Инфо по товарам'},
            {'method': 'POST', 'path': '/catalog/products/batch?shipmentcity=...', 'desc': 'Инфо по товарам (batch)'},
            {'method': 'GET', 'path': '/catalog/products/<item_ids>/certificates', 'desc': 'Сертификаты'},
            {'method': 'GET', 'path': '/logistic/shipment/cities', 'desc': 'Города отгрузки'},
            {'method': 'GET', 'path': '/logistic/stocks/locations?shipmentcity=...', 'desc': 'Местоположения товаров'},
            {'method': 'GET', 'path': '/content/<item_ids>', 'desc': 'Характеристики товаров'},
            {'method': 'GET', 'path': '/account/payers', 'desc': 'Плательщики'},
            {'method': 'GET', 'path': '/account/contactpersons', 'desc': 'Контактные лица'},
            {'method': 'GET', 'path': '/account/currencies/exchanges', 'desc': 'Курсы валют'},
        ]
    })

@app.route('/catalog/categories')
def get_categories():
    """2.2.1 - Получение дерева категорий"""
    result = client.get_categories()
    return jsonify(result)

@app.route('/catalog/categories/<categories>/products')
def get_categories_products(categories):
    """2.2.2 - Товары по категориям"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Параметр shipmentcity обязателен'}), 400
    
    # Получаем дополнительные параметры из запроса
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'false'),
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': request.args.get('includesale', 'false'),
        'includeuncondition': request.args.get('includeuncondition', 'false'),
        'includeunconditionalimages': request.args.get('includeunconditionalimages', 'false'),
        'includemissing': request.args.get('includemissing', 'false'),
        'withdescriptions': request.args.get('withdescriptions', 'true'),
        'locations': request.args.get('locations'),
        'producers': request.args.get('producers')
    }
    
    # Удаляем None значения
    params = {k: v for k, v in params.items() if v is not None}
    
    result = client.get_categories_products(categories, shipmentcity, params)
    return jsonify(result)

@app.route('/catalog/categories/batch/products', methods=['POST'])
def get_categories_products_batch():
    """2.2.3 - Товары по категориям (batch)"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Параметр shipmentcity обязателен'}), 400
    
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({'error': 'Требуется JSON массив категорий'}), 400
        
        # Получаем дополнительные параметры
        params = {
            'onlyavailable': request.args.get('onlyavailable', 'false'),
            'includeregular': request.args.get('includeregular', 'true'),
            'includesale': request.args.get('includesale', 'false'),
            'includeuncondition': request.args.get('includeuncondition', 'false'),
            'includeunconditionalimages': request.args.get('includeunconditionalimages', 'false'),
            'includemissing': request.args.get('includemissing', 'false'),
            'withdescriptions': request.args.get('withdescriptions', 'true'),
            'locations': request.args.get('locations'),
            'producers': request.args.get('producers')
        }
        params = {k: v for k, v in params.items() if v is not None}
        
        result = client.get_categories_products_batch(data, shipmentcity, params)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/catalog/products/<item_ids>')
def get_products_info(item_ids):
    """2.2.4 - Информация по товарам"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Параметр shipmentcity обязателен'}), 400
    
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'false'),
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': request.args.get('includesale', 'false'),
        'includeuncondition': request.args.get('includeuncondition', 'false'),
        'includeunconditionalimages': request.args.get('includeunconditionalimages', 'false'),
        'includemissing': request.args.get('includemissing', 'false'),
        'withdescriptions': request.args.get('withdescriptions', 'true'),
        'locations': request.args.get('locations'),
        'producers': request.args.get('producers')
    }
    params = {k: v for k, v in params.items() if v is not None}
    
    result = client.get_products_info(item_ids, shipmentcity, params)
    return jsonify(result)

@app.route('/catalog/products/batch', methods=['POST'])
def get_products_info_batch():
    """2.2.5 - Информация по товарам (batch)"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Параметр shipmentcity обязателен'}), 400
    
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({'error': 'Требуется JSON массив itemIds'}), 400
        
        params = {
            'onlyavailable': request.args.get('onlyavailable', 'false'),
            'includeregular': request.args.get('includeregular', 'true'),
            'includesale': request.args.get('includesale', 'false'),
            'includeuncondition': request.args.get('includeuncondition', 'false'),
            'includeunconditionalimages': request.args.get('includeunconditionalimages', 'false'),
            'includemissing': request.args.get('includemissing', 'false'),
            'withdescriptions': request.args.get('withdescriptions', 'true'),
            'locations': request.args.get('locations'),
            'producers': request.args.get('producers')
        }
        params = {k: v for k, v in params.items() if v is not None}
        
        result = client.get_products_info_batch(data, shipmentcity, params)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/catalog/products/<item_ids>/certificates')
def get_certificates(item_ids):
    """2.2.6 - Сертификаты на товары"""
    actuality = request.args.get('actuality', 'actual')
    result = client.get_certificates(item_ids, actuality)
    return jsonify(result)

@app.route('/catalog/products/batch/certificates', methods=['POST'])
def get_certificates_batch():
    """2.2.7 - Сертификаты на товары (batch)"""
    actuality = request.args.get('actuality', 'actual')
    
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({'error': 'Требуется JSON массив itemIds'}), 400
        
        result = client.get_certificates_batch(data, actuality)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ================ РУЧКИ ЛОГИСТИКИ ================

@app.route('/logistic/shipment/cities')
def get_shipment_cities():
    """2.3.1/4.3.3 - Города отгрузки"""
    result = client.get_shipment_cities()
    return jsonify(result)

@app.route('/logistic/stocks/locations')
def get_stock_locations():
    """2.3.2 - Местоположения товаров"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Параметр shipmentcity обязателен'}), 400
    
    result = client.get_stock_locations(shipmentcity)
    return jsonify(result)

@app.route('/logistic/stocks/reserveplaces')
def get_reserve_places():
    """4.3.4 - Места резервирования"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Параметр shipmentcity обязателен'}), 400
    
    result = client.get_reserve_places(shipmentcity)
    return jsonify(result)

@app.route('/logistic/shipment/pickup-points')
def get_pickup_points():
    """7.3.5 - Пункты выдачи"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Параметр shipmentcity обязателен'}), 400
    
    result = client.get_pickup_points(shipmentcity)
    return jsonify(result)

@app.route('/logistic/shipment/delivery-addresses')
def get_delivery_addresses():
    """7.3.8 - Адреса доставки"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Параметр shipmentcity обязателен'}), 400
    
    result = client.get_delivery_addresses(shipmentcity)
    return jsonify(result)

# ================ РУЧКИ КОНТЕНТА ================

@app.route('/content/<item_ids>')
def get_content(item_ids):
    """3.2.1 - Характеристики товаров"""
    result = client.get_content(item_ids)
    return jsonify(result)

@app.route('/content/batch', methods=['POST'])
def get_content_batch():
    """3.2.2 - Характеристики товаров (batch)"""
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({'error': 'Требуется JSON массив itemIds'}), 400
        
        result = client.get_content_batch(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/content/changes')
def get_content_changes():
    """3.2.3 - Изменения в контенте"""
    from_date = request.args.get('from')
    if not from_date:
        return jsonify({'error': 'Параметр from обязателен (дата в формате ДД/ММ/ГГГГ)'}), 400
    
    result = client.get_content_changes(from_date)
    return jsonify(result)

# ================ РУЧКИ АККАУНТА ================

@app.route('/account/payers')
def get_payers():
    """4.3.1 - Плательщики"""
    result = client.get_payers()
    return jsonify(result)

@app.route('/account/contactpersons')
def get_contact_persons():
    """4.3.2 - Контактные лица"""
    result = client.get_contact_persons()
    return jsonify(result)

@app.route('/account/currencies/exchanges')
def get_currency_exchanges():
    """4.3.5 - Курсы валют"""
    result = client.get_currency_exchanges()
    return jsonify(result)

@app.route('/account/finances')
def get_finances():
    """7.3.3 - Кредитные средства"""
    result = client.get_finances()
    return jsonify(result)

@app.route('/account/consignees')
def get_consignees():
    """7.3.4 - Грузополучатели"""
    result = client.get_consignees()
    return jsonify(result)

# ================ СЕРВИСНЫЕ РУЧКИ ================

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'service': 'ocs-api-proxy',
        'api_key_configured': bool(API_KEY)
    })

@app.route('/diagnostic')
def diagnostic():
    """Диагностика соединения"""
    # Проверяем базовые методы
    cities_result = client.get_shipment_cities()
    categories_result = client.get_categories()
    
    return jsonify({
        'api_status': {
            'key_configured': bool(API_KEY),
            'base_url': BASE_URL
        },
        'connection_tests': {
            'cities_endpoint': {
                'success': 'error' not in cities_result,
                'status': 'error' in cities_result and cities_result.get('status_code') or 200
            },
            'categories_endpoint': {
                'success': 'error' not in categories_result,
                'status': 'error' in categories_result and categories_result.get('status_code') or 200
            }
        },
        'cache_info': {
            'size': len(cache),
            'keys': list(cache.keys())[:5] if cache else []
        },
        'suggestions': [
            '1. Проверьте API ключ в настройках Render',
            '2. Убедитесь, что IP адреса Render добавлены в белый список OCS',
            '3. Проверьте URL API (рабочий/тестовый)'
        ]
    })

@app.route('/cache/clear')
def clear_cache():
    """Очистка кэша"""
    cache.clear()
    return jsonify({'message': 'Cache cleared', 'timestamp': datetime.now().isoformat()})

@app.route('/examples')
def examples():
    """Примеры запросов"""
    return jsonify({
        'examples': {
            'get_cities': 'GET /logistic/shipment/cities',
            'get_categories': 'GET /catalog/categories',
            'get_products_by_category': 'GET /catalog/categories/all/products?shipmentcity=Москва&includeregular=true',
            'get_products_info': 'GET /catalog/products/1000459749,1000459646?shipmentcity=Москва',
            'get_certificates': 'GET /catalog/products/1000459619/certificates',
            'get_content': 'GET /content/1000459619',
            'get_payers': 'GET /account/payers',
            'get_currency_rates': 'GET /account/currencies/exchanges'
        },
        'note': 'Для методов с параметром shipmentcity используйте города из /logistic/shipment/cities'
    })

# Обработчики ошибок
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found', 'docs': '/'}), 404

@app.errorhandler(400)
def bad_request(error):
    return jsonify({'error': 'Bad request', 'message': str(error)}), 400

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        threaded=True
    )