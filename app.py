import os
import requests
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from datetime import datetime, timedelta
import time
from functools import wraps
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============ КОНФИГУРАЦИЯ ============
API_KEY = os.getenv('OCS_API_KEY', '').strip()
BASE_URL = os.getenv('OCS_BASE_URL', 'https://connector.b2b.ocs.ru/api/v2').strip()

# Таймауты (connect, read) - оптимизированы для пагинации
TIMEOUTS = {
    'default': (10, 30),
    'categories': (10, 45),
    'categories_page': (5, 20),      # ⭐ Быстрее для одной страницы категорий
    'products_heavy': (15, 60),
    'products_light': (10, 40),
    'products_page': (10, 45),       # ⭐ Для страницы товаров (300 шт)
    'product_info': (5, 20),
    'cities': (5, 15),
    'currency': (5, 15),
}

# Кэш с TTL
cache = {}
CACHE_TTL = int(os.getenv('CACHE_TTL', 300))

# Статистика запросов
request_stats = {}

# Настройки пагинации
PAGINATION = {
    'categories_per_page': 20,       # ⭐ 20 категорий на страницу
    'products_per_page': 300,        # ⭐ 300 товаров на страницу
    'max_products_per_page': 500,    # Максимум для безопасности
}

# ============ НАСТРОЙКА SESSION ============
def create_session():
    """Создаёт оптимизированную сессию с пулингом и ретраями"""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=1,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "HEAD", "OPTIONS"]
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=20,
        pool_maxsize=50,
        pool_block=False
    )
    
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    
    if API_KEY:
        session.headers.update({
            'accept': 'application/json',
            'X-API-Key': API_KEY,
            'User-Agent': 'OCS-API-Proxy/2.3-pagination',
            'Connection': 'keep-alive'
        })
        logger.info(f"API Key configured: {API_KEY[:8]}...")
    else:
        logger.warning("⚠️ OCS_API_KEY not set - requests may fail with 403")
    
    return session

client_session = create_session()

# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
def log_statistics(category, success, response_time, status_code=None):
    """Логируем статистику по запросам"""
    if category not in request_stats:
        request_stats[category] = {
            'total': 0, 'success': 0, 'failures': 0,
            'timeouts': 0, 'avg_time': 0, 'last_times': [],
            'last_status': None
        }
    
    stats = request_stats[category]
    stats['total'] += 1
    stats['last_status'] = status_code
    
    if success:
        stats['success'] += 1
        stats['last_times'].append(response_time)
        if len(stats['last_times']) > 10:
            stats['last_times'].pop(0)
        stats['avg_time'] = sum(stats['last_times']) / len(stats['last_times'])
    else:
        stats['failures'] += 1

def get_timeout_for_endpoint(endpoint, category=None):
    """Возвращает подходящие таймауты для эндпоинта"""
    if '/categories' in endpoint and '/products' not in endpoint:
        if '/page/' in endpoint:
            return TIMEOUTS['categories_page']  # ⭐ Быстрее для пагинации
        return TIMEOUTS['categories']
    elif '/products' in endpoint:
        if '/page/' in endpoint:
            return TIMEOUTS['products_page']  # ⭐ Для пагинации товаров
        if category in ['V08', 'V09', 'V02', 'V05']:
            return TIMEOUTS['products_heavy']
        return TIMEOUTS['products_light']
    elif '/products/' in endpoint and endpoint.count('/') == 4:
        return TIMEOUTS['product_info']
    elif '/cities' in endpoint:
        return TIMEOUTS['cities']
    elif '/currencies' in endpoint:
        return TIMEOUTS['currency']
    return TIMEOUTS['default']

def get_cache_key(prefix, **params):
    """Генерирует ключ кэша из параметров"""
    sorted_params = sorted((k, str(v)) for k, v in params.items())
    param_str = '&'.join(f"{k}={v}" for k, v in sorted_params)
    return f"{prefix}:{param_str}" if param_str else prefix

def create_pagination_response(data, page, per_page, total, category=None, extra_info=None):
    """Создаёт стандартизированный ответ с пагинацией"""
    total_pages = max(1, (total + per_page - 1) // per_page)
    
    response = {
        'result': data,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1,
            'next_page': page + 1 if page < total_pages else None,
            'prev_page': page - 1 if page > 1 else None
        },
        'timestamp': datetime.now().isoformat()
    }
    
    if category:
        response['category'] = category
    
    if extra_info:
        response.update(extra_info)
    
    return response

# ============ КЛАСС OCS CLIENT ============
class OCSClient:
    def __init__(self, session=None):
        self.session = session or create_session()
        self._categories_cache = None
        self._categories_cache_time = None
    
    def _make_request_with_retry(self, method, endpoint, params=None, data=None,
                                  category=None, max_retries=3, base_delay=0.5):
        """Запрос с умными ретраями и кэш-фоллбэком"""
        url = f"{BASE_URL}{endpoint}"
        timeout = get_timeout_for_endpoint(endpoint, category)
        cache_key = get_cache_key(endpoint.replace('/', '_'), **(params or {}))
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    wait_time = base_delay * (2 ** (attempt - 1))
                    logger.info(f"Retry {attempt}/{max_retries} for {endpoint}, waiting {wait_time:.1f}s")
                    time.sleep(wait_time)
                
                start_time = time.time()
                logger.debug(f"Request {method} {url} with params: {params}")
                
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    timeout=timeout,
                    headers={'Accept': 'application/json'}
                )
                
                elapsed = time.time() - start_time
                
                if response.status_code == 200:
                    logger.info(f"✓ Success: {endpoint} in {elapsed:.2f}s")
                    return response.json(), elapsed, True, response.status_code
                elif response.status_code == 429:
                    retry_after = int(response.headers.get('retry-after', 60))
                    logger.warning(f"⚠️ Rate limit (429) for {endpoint}, waiting {retry_after}s")
                    if attempt < max_retries:
                        time.sleep(min(retry_after, 120))
                        continue
                elif response.status_code in [401, 403]:
                    logger.error(f"✗ Auth error {response.status_code} for {endpoint}")
                    return {'error': f'Authentication failed ({response.status_code})'}, 0, False, response.status_code
                else:
                    logger.warning(f"⚠️ HTTP {response.status_code} for {endpoint}")
                    if response.status_code == 404:
                        return {'error': 'Not found', 'status': 404}, elapsed, False, response.status_code
                        
            except requests.exceptions.Timeout as e:
                logger.warning(f"⏱️ Timeout attempt {attempt + 1}/{max_retries + 1} for {endpoint}: {str(e)}")
                
                if cache_key in cache:
                    cached_data, cached_time = cache[cache_key]
                    if datetime.now().timestamp() - cached_time < CACHE_TTL * 2:
                        logger.info(f"📦 Cache fallback for {endpoint} (stale data)")
                        return cached_data, 0, True, 200
                
                if attempt == max_retries:
                    log_statistics(category or endpoint, False, 0, 'timeout')
                    return {'error': f'Request timeout after {max_retries + 1} attempts'}, 0, False, None
                    
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"🔌 Connection error attempt {attempt + 1}: {str(e)}")
                if attempt == max_retries:
                    log_statistics(category or endpoint, False, 0, 'connection')
                    return {'error': f'Connection failed: {str(e)}'}, 0, False, None
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Request error: {str(e)}")
                if attempt == max_retries:
                    log_statistics(category or endpoint, False, 0, 'error')
                    return {'error': str(e)}, 0, False, None
                    
            except Exception as e:
                logger.exception(f"💥 Unexpected error: {str(e)}")
                if attempt == max_retries:
                    return {'error': f'Unexpected error: {str(e)}'}, 0, False, None
        
        log_statistics(category or endpoint, False, 0, 'max_retries')
        return {'error': 'Max retries exceeded'}, 0, False, None
    
    def _get_all_categories_flat(self):
        """Получает все категории плоским списком (для пагинации)"""
        # Проверка внутреннего кэша
        if self._categories_cache and self._categories_cache_time:
            if datetime.now().timestamp() - self._categories_cache_time < CACHE_TTL:
                return self._categories_cache
        
        # Загрузка дерева категорий
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', '/catalog/categories',
            category='categories_tree',
            max_retries=3
        )
        
        if not success or 'error' in result:
            return None
        
        # Преобразование дерева в плоский список
        flat_categories = []
        
        def flatten_tree(tree, level=0):
            if isinstance(tree, dict):
                if 'category' in tree:
                    flat_categories.append({
                        'category': tree.get('category'),
                        'name': tree.get('name'),
                        'level': level
                    })
                if 'children' in tree:
                    for child in tree['children']:
                        flatten_tree(child, level + 1)
            elif isinstance(tree, list):
                for item in tree:
                    flatten_tree(item, level)
        
        flatten_tree(result)
        
        # Кэширование
        self._categories_cache = flat_categories
        self._categories_cache_time = datetime.now().timestamp()
        
        logger.info(f"📦 Loaded {len(flat_categories)} categories for pagination")
        return flat_categories
    
    def get_categories_paginated(self, page=1, per_page=None):
        """⭐ Пагинация категорий - 20 элементов на страницу"""
        if per_page is None:
            per_page = PAGINATION['categories_per_page']
        
        per_page = min(per_page, 50)  # Макс 50 для категорий
        
        # Получаем все категории
        all_categories = self._get_all_categories_flat()
        
        if all_categories is None:
            # Fallback на статичный список
            main_categories = [
                {'category': 'V01', 'name': 'Apple', 'level': 0},
                {'category': 'V02', 'name': 'Ноутбуки', 'level': 0},
                {'category': 'V03', 'name': 'Компьютеры', 'level': 0},
                {'category': 'V04', 'name': 'Мониторы', 'level': 0},
                {'category': 'V05', 'name': 'Комплектующие', 'level': 0},
                {'category': 'V06', 'name': 'Периферия', 'level': 0},
                {'category': 'V07', 'name': 'Сетевое оборудование', 'level': 0},
                {'category': 'V08', 'name': 'Серверы', 'level': 0},
                {'category': 'V09', 'name': 'Офисная техника', 'level': 0},
                {'category': 'V10', 'name': 'Программное обеспечение', 'level': 0},
                {'category': 'V11', 'name': 'Гаджеты', 'level': 0},
                {'category': 'V12', 'name': 'Телефоны', 'level': 0},
                {'category': 'V13', 'name': 'ИБП', 'level': 0},
                {'category': 'V70', 'name': 'Электронные компоненты', 'level': 0}
            ]
            all_categories = main_categories
        
        total = len(all_categories)
        
        # Пагинация
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        if start_idx >= total:
            return create_pagination_response(
                data=[],
                page=page,
                per_page=per_page,
                total=total,
                category='all',
                extra_info={'note': 'Page out of range'}
            )
        
        paginated_categories = all_categories[start_idx:end_idx]
        
        logger.info(f"📦 Categories page {page}: returning {len(paginated_categories)} of {total}")
        
        return create_pagination_response(
            data=paginated_categories,
            page=page,
            per_page=per_page,
            total=total,
            category='all'
        )
    
    def get_categories_tree(self):
        """Дерево категорий (полное)"""
        cache_key = 'categories_tree'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"📦 Cache hit for categories tree")
                return data
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', '/catalog/categories',
            category='categories_tree',
            max_retries=3
        )
        
        log_statistics('categories_tree', success, elapsed, status)
        
        if success and 'error' not in result:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_categories_light(self):
        """Основные категории (верхний уровень)"""
        cache_key = 'categories_light'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        tree = self.get_categories_tree()
        
        if 'error' in tree:
            main_categories = [
                {'category': 'V01', 'name': 'Apple'},
                {'category': 'V02', 'name': 'Ноутбуки'},
                {'category': 'V03', 'name': 'Компьютеры'},
                {'category': 'V04', 'name': 'Мониторы'},
                {'category': 'V05', 'name': 'Комплектующие'},
                {'category': 'V06', 'name': 'Периферия'},
                {'category': 'V07', 'name': 'Сетевое оборудование'},
                {'category': 'V08', 'name': 'Серверы'},
                {'category': 'V09', 'name': 'Офисная техника'},
                {'category': 'V10', 'name': 'Программное обеспечение'},
                {'category': 'V11', 'name': 'Гаджеты'},
                {'category': 'V12', 'name': 'Телефоны'},
                {'category': 'V13', 'name': 'ИБП'},
                {'category': 'V70', 'name': 'Электронные компоненты'}
            ]
            result = {'categories': main_categories}
            cache[cache_key] = (result, datetime.now().timestamp())
            return result
        
        def extract_main_categories(category_tree, level=0):
            main_cats = []
            if isinstance(category_tree, dict):
                if 'category' in category_tree and level == 0:
                    main_cats.append({
                        'category': category_tree.get('category'),
                        'name': category_tree.get('name')
                    })
                if 'children' in category_tree:
                    for child in category_tree['children']:
                        main_cats.extend(extract_main_categories(child, level + 1))
            elif isinstance(category_tree, list):
                for item in category_tree:
                    main_cats.extend(extract_main_categories(item, level))
            return main_cats
        
        main_cats = extract_main_categories(tree)
        result = {'categories': main_cats}
        cache[cache_key] = (result, datetime.now().timestamp())
        return result
    
    def get_products_by_category(self, category, shipmentcity, **params):
        """Товары по категории (все)"""
        cache_key = get_cache_key(f"products_{category}_{shipmentcity}", **params)
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"📦 Cache hit for category {category}")
                return data
        
        max_retries = 3 if category in ['V08', 'V09', 'V02', 'V05'] else 2
        endpoint = f"/catalog/categories/{category}/products"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        
        if 'withdescriptions' not in query_params:
            query_params['withdescriptions'] = 'false'
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', endpoint,
            params=query_params,
            category=category,
            max_retries=max_retries
        )
        
        log_statistics(category, success, elapsed, status)
        
        if success and 'error' not in result and isinstance(result, dict):
            if 'result' in result and isinstance(result['result'], list):
                logger.info(f"📦 Category {category}: returning {len(result['result'])} products")
                cache[cache_key] = (result, datetime.now().timestamp())
                return result
    
    def get_products_paginated(self, category, shipmentcity, page=1, per_page=None, **params):
        """⭐ Пагинация товаров - 300 элементов на страницу"""
        if per_page is None:
            per_page = PAGINATION['products_per_page']
        
        per_page = min(per_page, PAGINATION['max_products_per_page'])
        
        cache_key = get_cache_key(f"products_page_{category}_{shipmentcity}_p{page}_pp{per_page}", **params)
        
        # Проверка кэша страницы
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"📦 Cache hit for products page {page}")
                return data
        
        # Получаем все товары категории
        all_products = self.get_products_by_category(category, shipmentcity, **params)
        
        if 'error' in all_products:
            return all_products
        
        if 'result' not in all_products or not isinstance(all_products['result'], list):
            return {'error': 'Invalid response format', 'data': all_products}
        
        products = all_products['result']
        total = len(products)
        
        # Пагинация
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        if start_idx >= total:
            return create_pagination_response(
                data=[],
                page=page,
                per_page=per_page,
                total=total,
                category=category,
                extra_info={'shipmentcity': shipmentcity}
            )
        
        paginated_products = products[start_idx:end_idx]
        
        logger.info(f"📦 Products page {page}: returning {len(paginated_products)} of {total}")
        
        response = create_pagination_response(
            data=paginated_products,
            page=page,
            per_page=per_page,
            total=total,
            category=category,
            extra_info={'shipmentcity': shipmentcity}
        )
        
        # Кэширование страницы
        cache[cache_key] = (response, datetime.now().timestamp())
        
        return response
    
    def get_product_info(self, item_id, shipmentcity, **params):
        """Информация по товару"""
        cache_key = f"product_{item_id}_{shipmentcity}"
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        endpoint = f"/catalog/products/{item_id}"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', endpoint,
            params=query_params,
            category='product_info',
            max_retries=2
        )
        
        if success and 'error' not in result:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_shipment_cities(self):
        """Города отгрузки"""
        cache_key = 'shipment_cities'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', '/logistic/shipment/cities',
            category='cities',
            max_retries=2
        )
        
        if success and 'error' not in result:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_currency_exchanges(self):
        """Курсы валют"""
        cache_key = 'currency_exchanges'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < 300:
                return data
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', '/account/currencies/exchanges',
            category='currency',
            max_retries=2
        )
        
        if success and 'error' not in result:
            cache[cache_key] = (result, datetime.now().timestamp() + 300)
        
        return result
    
    def get_category_stats(self):
        """Статистика по категориям"""
        return {
            'total_categories_tracked': len(request_stats),
            'categories': request_stats,
            'problematic_categories': [
                cat for cat, stats in request_stats.items()
                if stats.get('failures', 0) > stats.get('success', 0)
            ]
        }
    
    def clear_cache(self, pattern=None):
        """Очистка кэша по паттерну"""
        if pattern:
            keys_to_delete = [k for k in cache.keys() if pattern in k]
            for k in keys_to_delete:
                del cache[k]
            return len(keys_to_delete)
        else:
            count = len(cache)
            cache.clear()
            # Сброс кэша категорий
            self._categories_cache = None
            self._categories_cache_time = None
            return count

client = OCSClient(client_session)

# ============ API ENDPOINTS ============
@app.route('/')
def home():
    return jsonify({
        'service': 'OCS API Proxy',
        'status': 'operational',
        'version': '2.3-pagination',
        'features': [
            '✅ Categories pagination (20 per page)',
            '✅ Products pagination (300 per page)',
            '✅ Reduced timeouts for paginated requests',
            '✅ Exponential backoff retries',
            '✅ Cache fallback on timeout',
            '✅ Connection pooling (50 max)'
        ],
        'pagination': {
            'categories_per_page': PAGINATION['categories_per_page'],
            'products_per_page': PAGINATION['products_per_page'],
            'max_products_per_page': PAGINATION['max_products_per_page']
        },
        'endpoints': {
            'cities': '/api/cities',
            'categories_tree': '/api/categories',
            'categories_light': '/api/categories/light',
            'categories_paginated': '/api/categories/page/<int:page>?per_page=20',
            'products': '/api/categories/<category>/products?shipmentcity=...',
            'products_paginated': '/api/categories/<category>/products/page/<int:page>?shipmentcity=...&per_page=300',
            'product_info': '/api/products/<item_id>?shipmentcity=...',
            'currency': '/api/currency',
            'stats': '/api/stats',
            'health': '/api/health',
            'cache_clear': '/api/cache/clear'
        },
        'tips': [
            'Use /api/categories/page/1 for fast category loading (no timeout)',
            'Use /api/categories/<cat>/products/page/1?per_page=300 for products',
            'Use ?withdescriptions=false for faster product requests',
            'Check /api/health for service status'
        ]
    })

@app.route('/api/cities')
def get_cities():
    result = client.get_shipment_cities()
    return jsonify(result)

@app.route('/api/categories')
def get_categories():
    """Полное дерево категорий"""
    result = client.get_categories_tree()
    return jsonify(result)

@app.route('/api/categories/light')
def get_categories_light():
    """Основные категории — верхний уровень"""
    result = client.get_categories_light()
    return jsonify(result)

@app.route('/api/categories/page/<int:page>')
def get_categories_paginated(page):
    """⭐ Пагинация категорий - 20 элементов на страницу"""
    per_page = request.args.get('per_page', PAGINATION['categories_per_page'], type=int)
    result = client.get_categories_paginated(page, per_page)
    return jsonify(result)

@app.route('/api/categories/<category>/products')
def get_category_products(category):
    """Товары по категории (все)"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': 'false',
        'includeuncondition': 'false',
        'includemissing': 'false',
        'withdescriptions': request.args.get('withdescriptions', 'false'),
    }
    
    for param in ['locations', 'producers', 'includesale', 'includeuncondition', 'includemissing']:
        if param in request.args:
            params[param] = request.args.get(param)
    
    result = client.get_products_by_category(category, shipmentcity, **params)
    return jsonify(result)

@app.route('/api/categories/<category>/products/page/<int:page>')
def get_category_products_paginated(category, page):
    """⭐ Пагинация товаров - 300 элементов на страницу"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    per_page = request.args.get('per_page', PAGINATION['products_per_page'], type=int)
    per_page = min(per_page, PAGINATION['max_products_per_page'])
    
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'withdescriptions': request.args.get('withdescriptions', 'false'),
    }
    
    result = client.get_products_paginated(category, shipmentcity, page, per_page, **params)
    return jsonify(result)

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

@app.route('/api/currency')
def get_currency():
    result = client.get_currency_exchanges()
    return jsonify(result)

@app.route('/api/stats')
def get_stats():
    stats = client.get_category_stats()
    cache_info = {
        'total_entries': len(cache),
        'keys': list(cache.keys())[:20]
    }
    return jsonify({
        'request_statistics': stats,
        'cache_info': cache_info,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/health')
def health():
    """Health check с проверкой подключения"""
    health_status = 'healthy'
    checks = {}
    
    try:
        cities = client.get_shipment_cities()
        checks['cities_endpoint'] = 'ok' if 'error' not in cities else 'failed'
        if checks['cities_endpoint'] == 'failed':
            health_status = 'degraded'
    except Exception as e:
        checks['cities_endpoint'] = f'error: {str(e)}'
        health_status = 'unhealthy'
    
    checks['cache'] = 'ok' if len(cache) > 0 else 'empty'
    
    problematic = [
        cat for cat, stats in request_stats.items()
        if stats.get('timeouts', 0) > 2 or stats.get('failures', 0) > stats.get('success', 0)
    ]
    
    total_req = sum(s.get('total', 0) for s in request_stats.values())
    total_ok = sum(s.get('success', 0) for s in request_stats.values())
    
    return jsonify({
        'status': health_status,
        'checks': checks,
        'problematic_categories': problematic[:5],
        'timestamp': datetime.now().isoformat(),
        'uptime_checks': {
            'total_requests': total_req,
            'success_rate': f"{total_ok / max(1, total_req):.1%}" if total_req > 0 else 'N/A'
        },
        'config': {
            'cache_ttl': CACHE_TTL,
            'timeouts': TIMEOUTS,
            'pagination': PAGINATION
        }
    })

@app.route('/api/cache/clear', methods=['POST', 'GET'])
def clear_cache():
    """Очистка кэша"""
    pattern = request.args.get('pattern')
    cleared = client.clear_cache(pattern)
    return jsonify({
        'message': f'Cache cleared: {cleared} entries',
        'cleared_entries': cleared,
        'pattern': pattern,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/tips')
def get_tips():
    return jsonify({
        'performance_tips': [
            'Use /api/categories/page/1 for fast category loading (20 items)',
            'Use /api/categories/<cat>/products/page/1?per_page=300 for products',
            'Use ?withdescriptions=false for 2-3x faster product requests',
            'Cache responses client-side (localStorage/IndexedDB)'
        ],
        'pagination_info': {
            'categories': f"{PAGINATION['categories_per_page']} per page",
            'products': f"{PAGINATION['products_per_page']} per page (max {PAGINATION['max_products_per_page']})"
        },
        'timeout_info': {
            'categories_page': f"{TIMEOUTS['categories_page']}s (connect, read)",
            'products_page': f"{TIMEOUTS['products_page']}s for 300 products"
        },
        'recommended_flow': [
            '1. GET /api/cities',
            '2. GET /api/categories/page/1 (then page/2, page/3...)',
            '3. GET /api/categories/{code}/products/page/1?shipmentcity=...&per_page=300',
            '4. GET /api/products/{id}?shipmentcity=... for details'
        ]
    })

@app.route('/api/debug/connection')
def debug_connection():
    """Диагностика подключения к OCS API"""
    import socket
    import ssl
    
    result = {
        'env_vars': {
            'OCS_API_KEY_set': bool(API_KEY),
            'BASE_URL': BASE_URL,
            'CACHE_TTL': CACHE_TTL
        },
        'dns': {},
        'ssl': {},
        'test_request': {}
    }
    
    try:
        ip = socket.gethostbyname('connector.b2b.ocs.ru')
        result['dns']['resolved'] = ip
    except Exception as e:
        result['dns']['error'] = str(e)
    
    try:
        context = ssl.create_default_context()
        with socket.create_connection(('connector.b2b.ocs.ru', 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname='connector.b2b.ocs.ru') as ssock:
                result['ssl']['version'] = ssock.version()
                result['ssl']['cipher'] = ssock.cipher()[0]
    except Exception as e:
        result['ssl']['error'] = str(e)
    
    try:
        test_resp = client_session.get(
            f"{BASE_URL}/catalog/categories",
            headers={'accept': 'application/json'},
            timeout=10
        )
        result['test_request'] = {
            'status_code': test_resp.status_code,
            'headers_sent': dict(client_session.headers)
        }
    except Exception as e:
        result['test_request']['error'] = str(e)
    
    return jsonify(result)

# Редирект старых URL
@app.route('/content/<path:path>')
@app.route('/catalog/<path:path>')
@app.route('/logistic/<path:path>')
def old_urls_redirect(path):
    return jsonify({
        'error': 'Endpoint moved',
        'new_location': '/api/...',
        'documentation': '/',
        'timestamp': datetime.now().isoformat()
    }), 404

@app.errorhandler(404)
def not_found(e):
    return jsonify({
        'error': 'Not found',
        'available_endpoints': [
            '/api/cities', '/api/categories', '/api/categories/light',
            '/api/categories/page/<page>', '/api/categories/<category>/products',
            '/api/categories/<category>/products/page/<page>',
            '/api/products/<item_id>', '/api/currency', '/api/stats', '/api/health'
        ]
    }), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal error: {str(e)}")
    return jsonify({
        'error': 'Internal server error',
        'timestamp': datetime.now().isoformat()
    }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    logger.info(f"Starting OCS API Proxy v2.3-pagination on port {port}")
    logger.info(f"Base URL: {BASE_URL}")
    logger.info(f"Cache TTL: {CACHE_TTL}s")
    logger.info(f"Categories per page: {PAGINATION['categories_per_page']}")
    logger.info(f"Products per page: {PAGINATION['products_per_page']}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        threaded=True
    )import os
import requests
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from datetime import datetime, timedelta
import time
from functools import wraps
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============ КОНФИГУРАЦИЯ ============
API_KEY = os.getenv('OCS_API_KEY', '').strip()
BASE_URL = os.getenv('OCS_BASE_URL', 'https://connector.b2b.ocs.ru/api/v2').strip()

# Таймауты (connect, read) - увеличены для стабильности
TIMEOUTS = {
    'default': (10, 30),           # 10с коннект, 30с чтение
    'categories': (10, 45),         # Дерево категорий может быть тяжёлым
    'products_heavy': (15, 60),     # V08, V09, V02 - большие категории
    'products_light': (10, 40),     # Обычные категории
    'product_info': (5, 20),        # Инфо по одному товару
    'cities': (5, 15),              # Города - лёгкий запрос
    'currency': (5, 15),            # Курсы валют
}

# Кэш с TTL
cache = {}
CACHE_TTL = int(os.getenv('CACHE_TTL', 300))  # 5 минут по умолчанию

# Статистика запросов
request_stats = {}

# ============ НАСТРОЙКА SESSION ============
def create_session():
    """Создаёт оптимизированную сессию с пулингом и ретраями"""
    session = requests.Session()
    
    # Стратегия ретраев на уровне urllib3 (для сетевых ошибок)
    retry_strategy = Retry(
        total=1,  # 1 дополнительный ретрай на уровне urllib3
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "HEAD", "OPTIONS"]
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=20,      # Количество пулов соединений
        pool_maxsize=50,          # Макс соединений в пуле
        pool_block=False          # Не блокировать при исчерпании пула
    )
    
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    
    # Заголовки по умолчанию
    if API_KEY:
        session.headers.update({
            'accept': 'application/json',
            'X-API-Key': API_KEY,
            'User-Agent': 'OCS-API-Proxy/2.2',
            'Connection': 'keep-alive'
        })
        logger.info(f"API Key configured: {API_KEY[:8]}...")
    else:
        logger.warning("⚠️ OCS_API_KEY not set - requests may fail with 403")
    
    return session

client_session = create_session()


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
def log_statistics(category, success, response_time, status_code=None):
    """Логируем статистику по запросам"""
    if category not in request_stats:
        request_stats[category] = {
            'total': 0, 'success': 0, 'failures': 0,
            'timeouts': 0, 'avg_time': 0, 'last_times': [],
            'last_status': None
        }
    
    stats = request_stats[category]
    stats['total'] += 1
    stats['last_status'] = status_code
    
    if success:
        stats['success'] += 1
        stats['last_times'].append(response_time)
        if len(stats['last_times']) > 10:
            stats['last_times'].pop(0)
        stats['avg_time'] = sum(stats['last_times']) / len(stats['last_times'])
    else:
        stats['failures'] += 1


def get_timeout_for_endpoint(endpoint, category=None):
    """Возвращает подходящие таймауты для эндпоинта"""
    if '/categories' in endpoint and '/products' not in endpoint:
        return TIMEOUTS['categories']
    elif '/products' in endpoint:
        if category in ['V08', 'V09', 'V02', 'V05']:
            return TIMEOUTS['products_heavy']
        return TIMEOUTS['products_light']
    elif '/products/' in endpoint and endpoint.count('/') == 4:
        return TIMEOUTS['product_info']
    elif '/cities' in endpoint:
        return TIMEOUTS['cities']
    elif '/currencies' in endpoint:
        return TIMEOUTS['currency']
    return TIMEOUTS['default']


def get_cache_key(prefix, **params):
    """Генерирует ключ кэша из параметров"""
    sorted_params = sorted((k, str(v)) for k, v in params.items())
    param_str = '&'.join(f"{k}={v}" for k, v in sorted_params)
    return f"{prefix}:{param_str}" if param_str else prefix


# ============ КЛАСС OCS CLIENT ============
class OCSClient:
    def __init__(self, session=None):
        self.session = session or create_session()
    
    def _make_request_with_retry(self, method, endpoint, params=None, data=None, 
                               category=None, max_retries=3, base_delay=0.5):
        """
        Запрос с умными ретраями и кэш-фоллбэком
        - Экспоненциальная задержка между попытками
        - Возврат закэшированных данных при таймауте
        - Детальное логирование
        """
        url = f"{BASE_URL}{endpoint}"
        timeout = get_timeout_for_endpoint(endpoint, category)
        cache_key = get_cache_key(endpoint.replace('/', '_'), **(params or {}))
        
        for attempt in range(max_retries + 1):
            try:
                # Небольшая задержка перед повторными попытками (экспоненциальная)
                if attempt > 0:
                    wait_time = base_delay * (2 ** (attempt - 1))  # 0.5s, 1s, 2s, 4s
                    logger.info(f"Retry {attempt}/{max_retries} for {endpoint}, waiting {wait_time:.1f}s")
                    time.sleep(wait_time)
                
                start_time = time.time()
                
                logger.debug(f"Request {method} {url} with params: {params}")
                
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    timeout=timeout,
                    headers={'Accept': 'application/json'}
                )
                
                elapsed = time.time() - start_time
                
                if response.status_code == 200:
                    logger.info(f"✓ Success: {endpoint} in {elapsed:.2f}s")
                    return response.json(), elapsed, True, response.status_code
                elif response.status_code == 429:
                    # Rate limit — ждём указанное время
                    retry_after = int(response.headers.get('retry-after', 60))
                    logger.warning(f"⚠️ Rate limit (429) for {endpoint}, waiting {retry_after}s")
                    if attempt < max_retries:
                        time.sleep(min(retry_after, 120))  # Макс 2 минуты ожидания
                        continue
                elif response.status_code in [401, 403]:
                    logger.error(f"✗ Auth error {response.status_code} for {endpoint}")
                    return {'error': f'Authentication failed ({response.status_code})'}, 0, False, response.status_code
                else:
                    logger.warning(f"⚠️ HTTP {response.status_code} for {endpoint}")
                    # Для 404 и других ошибок возвращаем ответ как есть
                    if response.status_code == 404:
                        return {'error': 'Not found', 'status': 404}, elapsed, False, response.status_code
                    
            except requests.exceptions.Timeout as e:
                logger.warning(f"⏱️ Timeout attempt {attempt + 1}/{max_retries + 1} for {endpoint}: {str(e)}")
                
                # Фоллбэк на кэш при таймауте
                if cache_key in cache:
                    cached_data, cached_time = cache[cache_key]
                    # Разрешаем использовать кэш с двойным TTL при ошибке
                    if datetime.now().timestamp() - cached_time < CACHE_TTL * 2:
                        logger.info(f"📦 Cache fallback for {endpoint} (stale data)")
                        return cached_data, 0, True, 200  # Возвращаем как успех
                
                if attempt == max_retries:
                    log_statistics(category or endpoint, False, 0, 'timeout')
                    return {'error': f'Request timeout after {max_retries + 1} attempts'}, 0, False, None
                    
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"🔌 Connection error attempt {attempt + 1}: {str(e)}")
                if attempt == max_retries:
                    log_statistics(category or endpoint, False, 0, 'connection')
                    return {'error': f'Connection failed: {str(e)}'}, 0, False, None
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Request error: {str(e)}")
                if attempt == max_retries:
                    log_statistics(category or endpoint, False, 0, 'error')
                    return {'error': str(e)}, 0, False, None
                    
            except Exception as e:
                logger.exception(f"💥 Unexpected error: {str(e)}")
                if attempt == max_retries:
                    return {'error': f'Unexpected error: {str(e)}'}, 0, False, None
        
        # Достигнут лимит попыток
        log_statistics(category or endpoint, False, 0, 'max_retries')
        return {'error': 'Max retries exceeded'}, 0, False, None
    
    def get_categories_tree(self):
        """Дерево категорий"""
        cache_key = 'categories_tree'
        
        # Проверка кэша
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"📦 Cache hit for categories tree")
                return data
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', '/catalog/categories',
            category='categories_tree',
            max_retries=3
        )
        
        log_statistics('categories_tree', success, elapsed, status)
        
        if success and 'error' not in result:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_categories_light(self):
        """Лёгкий список основных категорий — без лимитов"""
        cache_key = 'categories_light'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        tree = self.get_categories_tree()
        
        if 'error' in tree:
            # Fallback: статичный список если API не отвечает
            main_categories = [
                {'category': 'V01', 'name': 'Apple'},
                {'category': 'V02', 'name': 'Ноутбуки'},
                {'category': 'V03', 'name': 'Компьютеры'},
                {'category': 'V04', 'name': 'Мониторы'},
                {'category': 'V05', 'name': 'Комплектующие'},
                {'category': 'V06', 'name': 'Периферия'},
                {'category': 'V07', 'name': 'Сетевое оборудование'},
                {'category': 'V08', 'name': 'Серверы'},
                {'category': 'V09', 'name': 'Офисная техника'},
                {'category': 'V10', 'name': 'Программное обеспечение'},
                {'category': 'V11', 'name': 'Гаджеты'},
                {'category': 'V12', 'name': 'Телефоны'},
                {'category': 'V13', 'name': 'ИБП'},
                {'category': 'V70', 'name': 'Электронные компоненты'}
            ]
            result = {'categories': main_categories}
            cache[cache_key] = (result, datetime.now().timestamp())
            return result
        
        def extract_main_categories(category_tree, level=0):
            main_cats = []
            if isinstance(category_tree, dict):
                if 'category' in category_tree and level == 0:
                    main_cats.append({
                        'category': category_tree.get('category'),
                        'name': category_tree.get('name')
                    })
                if 'children' in category_tree:
                    for child in category_tree['children']:
                        main_cats.extend(extract_main_categories(child, level + 1))
            elif isinstance(category_tree, list):
                for item in category_tree:
                    main_cats.extend(extract_main_categories(item, level))
            return main_cats
        
        main_cats = extract_main_categories(tree)
        result = {'categories': main_cats}  # ✅ Без [:20] — все категории
        
        cache[cache_key] = (result, datetime.now().timestamp())
        return result
    
    def get_products_by_category(self, category, shipmentcity, **params):
        """Товары по категории — без искусственных лимитов"""
        cache_key = get_cache_key(f"products_{category}_{shipmentcity}", **params)
        
        # Проверка кэша
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"📦 Cache hit for category {category}")
                return data
        
        max_retries = 3 if category in ['V08', 'V09', 'V02', 'V05'] else 2
        
        endpoint = f"/catalog/categories/{category}/products"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        
        # Оптимизация: по умолчанию без описаний
        if 'withdescriptions' not in query_params:
            query_params['withdescriptions'] = 'false'
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', endpoint,
            params=query_params,
            category=category,
            max_retries=max_retries
        )
        
        log_statistics(category, success, elapsed, status)
        
        if success and 'error' not in result and isinstance(result, dict):
            # ✅ Возвращаем ВСЕ товары из ответа API (без обрезки)
            if 'result' in result and isinstance(result['result'], list):
                logger.info(f"📦 Category {category}: returning {len(result['result'])} products")
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_products_paginated(self, category, shipmentcity, page=1, per_page=100, **params):
        """Пагинация на стороне прокси"""
        all_products = self.get_products_by_category(category, shipmentcity, **params)
        
        if 'error' in all_products:
            return all_products
        
        if 'result' not in all_products or not isinstance(all_products['result'], list):
            return {'error': 'Invalid response format', 'data': all_products}
        
        products = all_products['result']
        total = len(products)
        
        # Ограничиваем per_page разумным значением
        per_page = min(per_page, 500)
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        if start_idx >= total:
            return {
                'result': [],
                'pagination': {
                    'page': page, 'per_page': per_page, 'total': total,
                    'total_pages': max(1, (total + per_page - 1) // per_page),
                    'has_next': False, 'has_prev': page > 1
                }
            }
        
        paginated_products = products[start_idx:end_idx]
        
        return {
            'result': paginated_products,
            'pagination': {
                'page': page, 'per_page': per_page, 'total': total,
                'total_pages': max(1, (total + per_page - 1) // per_page),
                'has_next': end_idx < total, 'has_prev': page > 1
            },
            'category': category,
            'shipmentcity': shipmentcity
        }
    
    def get_product_info(self, item_id, shipmentcity, **params):
        """Информация по товару"""
        cache_key = f"product_{item_id}_{shipmentcity}"
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        endpoint = f"/catalog/products/{item_id}"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', endpoint,
            params=query_params,
            category='product_info',
            max_retries=2
        )
        
        if success and 'error' not in result:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_shipment_cities(self):
        """Города отгрузки"""
        cache_key = 'shipment_cities'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', '/logistic/shipment/cities',
            category='cities',
            max_retries=2
        )
        
        if success and 'error' not in result:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_currency_exchanges(self):
        """Курсы валют"""
        cache_key = 'currency_exchanges'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < 300:
                return data
        
        result, elapsed, success, status = self._make_request_with_retry(
            'GET', '/account/currencies/exchanges',
            category='currency',
            max_retries=2
        )
        
        if success and 'error' not in result:
            cache[cache_key] = (result, datetime.now().timestamp() + 300)
        
        return result
    
    def get_category_stats(self):
        """Статистика по категориям"""
        return {
            'total_categories_tracked': len(request_stats),
            'categories': request_stats,
            'problematic_categories': [
                cat for cat, stats in request_stats.items() 
                if stats.get('failures', 0) > stats.get('success', 0)
            ]
        }
    
    def clear_cache(self, pattern=None):
        """Очистка кэша по паттерну"""
        if pattern:
            keys_to_delete = [k for k in cache.keys() if pattern in k]
            for k in keys_to_delete:
                del cache[k]
            return len(keys_to_delete)
        else:
            count = len(cache)
            cache.clear()
            return count


client = OCSClient(client_session)


# ============ API ENDPOINTS ============

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS API Proxy',
        'status': 'operational',
        'version': '2.2-timeout-fix',
        'features': [
            '✅ No artificial limits on categories/products',
            '✅ Increased timeouts (up to 60s read)',
            '✅ Exponential backoff retries',
            '✅ Cache fallback on timeout',
            '✅ Connection pooling (50 max)',
            '✅ Smart timeout selection per endpoint'
        ],
        'endpoints': {
            'cities': '/api/cities',
            'categories': '/api/categories',
            'categories_light': '/api/categories/light',
            'products': '/api/categories/<category>/products?shipmentcity=...',
            'products_paginated': '/api/categories/<category>/products/page/<int:page>?shipmentcity=...&per_page=...',
            'product_info': '/api/products/<item_id>?shipmentcity=...',
            'currency': '/api/currency',
            'stats': '/api/stats',
            'health': '/api/health',
            'cache_clear': '/api/cache/clear'
        },
        'tips': [
            'Use ?withdescriptions=false for faster product requests',
            'Use pagination for large categories: ?page=1&per_page=100',
            'Client-side caching recommended for production',
            'Check /api/health for service status'
        ]
    })


@app.route('/api/cities')
def get_cities():
    result = client.get_shipment_cities()
    return jsonify(result)


@app.route('/api/categories')
def get_categories():
    """Полное дерево категорий"""
    result = client.get_categories_tree()
    return jsonify(result)


@app.route('/api/categories/light')
def get_categories_light():
    """Основные категории — БЕЗ лимита"""
    result = client.get_categories_light()
    return jsonify(result)


@app.route('/api/categories/<category>/products')
def get_category_products(category):
    """Товары по категории — БЕЗ лимита"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': 'false',
        'includeuncondition': 'false',
        'includemissing': 'false',
        'withdescriptions': request.args.get('withdescriptions', 'false'),
    }
    
    for param in ['locations', 'producers', 'includesale', 'includeuncondition', 'includemissing']:
        if param in request.args:
            params[param] = request.args.get(param)
    
    result = client.get_products_by_category(category, shipmentcity, **params)
    return jsonify(result)


@app.route('/api/categories/<category>/products/page/<int:page>')
def get_category_products_paginated(category, page):
    """Товары с пагинацией — per_page до 500"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    per_page = int(request.args.get('per_page', 100))
    per_page = min(per_page, 500)  # Макс 500 для производительности
    
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'withdescriptions': request.args.get('withdescriptions', 'false'),
    }
    
    result = client.get_products_paginated(category, shipmentcity, page, per_page, **params)
    return jsonify(result)


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


@app.route('/api/currency')
def get_currency():
    result = client.get_currency_exchanges()
    return jsonify(result)


@app.route('/api/stats')
def get_stats():
    stats = client.get_category_stats()
    cache_info = {
        'total_entries': len(cache),
        'keys': list(cache.keys())[:20]
    }
    
    return jsonify({
        'request_statistics': stats,
        'cache_info': cache_info,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/health')
def health():
    """Health check с проверкой подключения"""
    health_status = 'healthy'
    checks = {}
    
    # Быстрая проверка городов (лёгкий эндпоинт)
    try:
        cities = client.get_shipment_cities()
        checks['cities_endpoint'] = 'ok' if 'error' not in cities else 'failed'
        if checks['cities_endpoint'] == 'failed':
            health_status = 'degraded'
    except Exception as e:
        checks['cities_endpoint'] = f'error: {str(e)}'
        health_status = 'unhealthy'
    
    # Проверка кэша
    checks['cache'] = 'ok' if len(cache) > 0 else 'empty'
    
    # Проблемные категории
    problematic = [
        cat for cat, stats in request_stats.items()
        if stats.get('timeouts', 0) > 2 or stats.get('failures', 0) > stats.get('success', 0)
    ]
    
    total_req = sum(s.get('total', 0) for s in request_stats.values())
    total_ok = sum(s.get('success', 0) for s in request_stats.values())
    
    return jsonify({
        'status': health_status,
        'checks': checks,
        'problematic_categories': problematic[:5],
        'timestamp': datetime.now().isoformat(),
        'uptime_checks': {
            'total_requests': total_req,
            'success_rate': f"{total_ok / max(1, total_req):.1%}" if total_req > 0 else 'N/A'
        },
        'config': {
            'cache_ttl': CACHE_TTL,
            'timeouts': TIMEOUTS
        }
    })


@app.route('/api/cache/clear', methods=['POST', 'GET'])
def clear_cache():
    """Очистка кэша"""
    pattern = request.args.get('pattern')
    cleared = client.clear_cache(pattern)
    return jsonify({
        'message': f'Cache cleared: {cleared} entries',
        'cleared_entries': cleared,
        'pattern': pattern,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/tips')
def get_tips():
    return jsonify({
        'performance_tips': [
            'Use ?withdescriptions=false for 2-3x faster product requests',
            'Use pagination for large categories: ?page=1&per_page=100',
            'Cache responses client-side (localStorage/IndexedDB)',
            'Request only needed fields via API parameters'
        ],
        'timeout_info': {
            'categories': f"{TIMEOUTS['categories']}s (connect, read)",
            'products_heavy': f"{TIMEOUTS['products_heavy']}s for V08/V09/V02/V05",
            'products_light': f"{TIMEOUTS['products_light']}s for other categories"
        },
        'retry_policy': {
            'max_attempts': 3,
            'backoff': 'exponential (0.5s, 1s, 2s, 4s)',
            'cache_fallback': 'enabled on timeout'
        },
        'recommended_flow': [
            '1. GET /api/cities',
            '2. GET /api/categories/light',
            '3. GET /api/categories/{code}/products?shipmentcity=...&withdescriptions=false',
            '4. GET /api/products/{id}?shipmentcity=... for details'
        ]
    })


@app.route('/api/debug/connection')
def debug_connection():
    """Диагностика подключения к OCS API"""
    import socket
    import ssl
    
    result = {
        'env_vars': {
            'OCS_API_KEY_set': bool(API_KEY),
            'BASE_URL': BASE_URL,
            'CACHE_TTL': CACHE_TTL
        },
        'dns': {},
        'ssl': {},
        'test_request': {}
    }
    
    # DNS lookup
    try:
        ip = socket.gethostbyname('connector.b2b.ocs.ru')
        result['dns']['resolved'] = ip
    except Exception as e:
        result['dns']['error'] = str(e)
    
    # SSL check
    try:
        context = ssl.create_default_context()
        with socket.create_connection(('connector.b2b.ocs.ru', 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname='connector.b2b.ocs.ru') as ssock:
                result['ssl']['version'] = ssock.version()
                result['ssl']['cipher'] = ssock.cipher()[0]
    except Exception as e:
        result['ssl']['error'] = str(e)
    
    # Test request
    try:
        test_resp = client_session.get(
            f"{BASE_URL}/catalog/categories",
            headers={'accept': 'application/json'},
            timeout=10
        )
        result['test_request'] = {
            'status_code': test_resp.status_code,
            'headers_sent': dict(client_session.headers)
        }
    except Exception as e:
        result['test_request']['error'] = str(e)
    
    return jsonify(result)


# Редирект старых URL
@app.route('/content/<path:path>')
@app.route('/catalog/<path:path>')
@app.route('/logistic/<path:path>')
def old_urls_redirect(path):
    return jsonify({
        'error': 'Endpoint moved',
        'new_location': '/api/...',
        'documentation': '/',
        'timestamp': datetime.now().isoformat()
    }), 404


# Обработчик 404
@app.errorhandler(404)
def not_found(e):
    return jsonify({
        'error': 'Not found',
        'available_endpoints': [
            '/api/cities', '/api/categories', '/api/categories/light',
            '/api/categories/<category>/products', '/api/products/<item_id>',
            '/api/currency', '/api/stats', '/api/health'
        ]
    }), 404


# Обработчик 500
@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal error: {str(e)}")
    return jsonify({
        'error': 'Internal server error',
        'timestamp': datetime.now().isoformat()
    }), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    logger.info(f"Starting OCS API Proxy v2.2 on port {port}")
    logger.info(f"Base URL: {BASE_URL}")
    logger.info(f"Cache TTL: {CACHE_TTL}s")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        threaded=True
    )import os
import requests
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from datetime import datetime, timedelta
import time
from functools import wraps

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Конфигурация
API_KEY = os.getenv('OCS_API_KEY')
BASE_URL = os.getenv('OCS_BASE_URL', 'https://connector.b2b.ocs.ru/api/v2').strip()

# Кэш с TTL
cache = {}
CACHE_TTL = int(os.getenv('CACHE_TTL', 300))  # 5 минут по умолчанию

# Статистика запросов
request_stats = {}

def log_statistics(category, success, response_time):
    """Логируем статистику по запросам"""
    if category not in request_stats:
        request_stats[category] = {
            'total': 0, 'success': 0, 'failures': 0,
            'avg_time': 0, 'last_times': []
        }
    
    stats = request_stats[category]
    stats['total'] += 1
    
    if success:
        stats['success'] += 1
        stats['last_times'].append(response_time)
        if len(stats['last_times']) > 10:
            stats['last_times'].pop(0)
        stats['avg_time'] = sum(stats['last_times']) / len(stats['last_times'])
    else:
        stats['failures'] += 1


class OCSClient:
    def __init__(self):
        self.session = requests.Session()
        if API_KEY:
            self.session.headers.update({
                'accept': 'application/json',
                'X-API-Key': API_KEY,
                'User-Agent': 'OCS-API-Proxy/2.1'
            })
    
    def _make_request_with_retry(self, method, endpoint, params=None, data=None, 
                               max_retries=2, timeout=(5, 15)):
        """Запрос с ретраями для проблемных категорий"""
        for attempt in range(max_retries + 1):
            try:
                url = f"{BASE_URL}{endpoint}"
                
                if attempt > 0:
                    wait_time = 0.5 * attempt
                    logger.info(f"Retry {attempt} for {endpoint}, waiting {wait_time}s")
                    time.sleep(wait_time)
                
                start_time = time.time()
                
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    timeout=timeout
                )
                
                elapsed = time.time() - start_time
                
                if response.status_code == 200:
                    logger.info(f"Success: {endpoint} in {elapsed:.2f}s")
                    return response.json(), elapsed, True
                else:
                    logger.warning(f"HTTP {response.status_code} for {endpoint}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout attempt {attempt + 1} for {endpoint}")
                if attempt == max_retries:
                    return {'error': 'Request timeout after retries'}, 0, False
                    
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error attempt {attempt + 1}: {str(e)}")
                if attempt == max_retries:
                    return {'error': f'Connection failed: {str(e)}'}, 0, False
                    
            except Exception as e:
                logger.error(f"Error on attempt {attempt + 1}: {str(e)}")
                if attempt == max_retries:
                    return {'error': str(e)}, 0, False
        
        return {'error': 'Max retries exceeded'}, 0, False
    
    def get_categories_tree(self, max_retries=1):
        """Дерево категорий с ретраями"""
        cache_key = 'categories_tree'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"Cache hit for categories tree")
                return data
        
        result, elapsed, success = self._make_request_with_retry(
            'GET', '/catalog/categories',
            max_retries=max_retries,
            timeout=(5, 30)  # Увеличенный таймаут для полного дерева
        )
        
        log_statistics('categories_tree', success, elapsed)
        
        if success:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_categories_light(self):
        """Легкая версия — основные категории БЕЗ лимита"""
        cache_key = 'categories_light'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        tree = self.get_categories_tree()
        
        if 'error' in tree:
            # Fallback: статичный список если API не отвечает
            main_categories = [
                {'category': 'V01', 'name': 'Apple'},
                {'category': 'V02', 'name': 'Ноутбуки'},
                {'category': 'V03', 'name': 'Компьютеры'},
                {'category': 'V04', 'name': 'Мониторы'},
                {'category': 'V05', 'name': 'Комплектующие'},
                {'category': 'V06', 'name': 'Периферия'},
                {'category': 'V07', 'name': 'Сетевое оборудование'},
                {'category': 'V08', 'name': 'Серверы'},
                {'category': 'V09', 'name': 'Офисная техника'},
                {'category': 'V10', 'name': 'Программное обеспечение'},
                {'category': 'V11', 'name': 'Гаджеты'},
                {'category': 'V12', 'name': 'Телефоны'},
                {'category': 'V13', 'name': 'ИБП'},
                {'category': 'V70', 'name': 'Электронные компоненты'}
            ]
            result = {'categories': main_categories}
            cache[cache_key] = (result, datetime.now().timestamp())
            return result
        
        def extract_main_categories(category_tree, level=0):
            main_cats = []
            if isinstance(category_tree, dict):
                if 'category' in category_tree and level == 0:
                    main_cats.append({
                        'category': category_tree.get('category'),
                        'name': category_tree.get('name')
                    })
                if 'children' in category_tree:
                    for child in category_tree['children']:
                        main_cats.extend(extract_main_categories(child, level + 1))
            elif isinstance(category_tree, list):
                for item in category_tree:
                    main_cats.extend(extract_main_categories(item, level))
            return main_cats
        
        main_cats = extract_main_categories(tree)
        
        # ✅ УБРАНО: [:20] — возвращаем ВСЕ основные категории
        result = {'categories': main_cats}
        
        cache[cache_key] = (result, datetime.now().timestamp())
        return result
    
    def get_products_by_category(self, category, shipmentcity, **params):
        """Товары по категории — БЕЗ искусственных лимитов"""
        cache_key = f"products_{category}_{shipmentcity}_{str(sorted(params.items()))}"
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"Cache hit for category {category}")
                return data
        
        # Проблемные категории — больше ретраев и таймаут
        max_retries = 2 if category in ['V08', 'V09', 'V02'] else 1
        timeout = (5, 30) if category in ['V08', 'V09', 'V02'] else (5, 15)
        
        endpoint = f"/catalog/categories/{category}/products"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        
        # Оптимизация: по умолчанию без описаний для скорости
        if 'withdescriptions' not in query_params:
            query_params['withdescriptions'] = 'false'
        
        result, elapsed, success = self._make_request_with_retry(
            'GET', endpoint,
            params=query_params,
            max_retries=max_retries,
            timeout=timeout
        )
        
        log_statistics(category, success, elapsed)
        
        if success and isinstance(result, dict):
            # ✅ УБРАНО: ограничение на 100 товаров
            # Возвращаем все товары, которые прислал API
            if 'result' in result and isinstance(result['result'], list):
                logger.info(f"Category {category}: returning {len(result['result'])} products")
            
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_products_paginated(self, category, shipmentcity, page=1, per_page=100, **params):
        """Пагинация товаров — с увеличенным лимитом per_page"""
        all_products = self.get_products_by_category(category, shipmentcity, **params)
        
        if 'error' in all_products:
            return all_products
        
        if 'result' not in all_products or not isinstance(all_products['result'], list):
            return {'error': 'Invalid response format', 'data': all_products}
        
        products = all_products['result']
        total = len(products)
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        if start_idx >= total:
            return {
                'result': [],
                'pagination': {
                    'page': page, 'per_page': per_page, 'total': total,
                    'total_pages': max(1, (total + per_page - 1) // per_page),
                    'has_next': False, 'has_prev': page > 1
                }
            }
        
        paginated_products = products[start_idx:end_idx]
        
        return {
            'result': paginated_products,
            'pagination': {
                'page': page, 'per_page': per_page, 'total': total,
                'total_pages': max(1, (total + per_page - 1) // per_page),
                'has_next': end_idx < total, 'has_prev': page > 1
            },
            'category': category,
            'shipmentcity': shipmentcity
        }
    
    def get_product_info(self, item_id, shipmentcity, **params):
        """Информация по товару"""
        cache_key = f"product_{item_id}_{shipmentcity}"
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        endpoint = f"/catalog/products/{item_id}"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        
        result, elapsed, success = self._make_request_with_retry(
            'GET', endpoint, params=query_params, timeout=(3, 15)
        )
        
        if success:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_shipment_cities(self):
        """Города отгрузки"""
        cache_key = 'shipment_cities'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        result, elapsed, success = self._make_request_with_retry(
            'GET', '/logistic/shipment/cities', timeout=(3, 10)
        )
        
        if success:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_currency_exchanges(self):
        """Курсы валют"""
        cache_key = 'currency_exchanges'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < 300:
                return data
        
        result, elapsed, success = self._make_request_with_retry(
            'GET', '/account/currencies/exchanges', timeout=(3, 10)
        )
        
        if success:
            cache[cache_key] = (result, datetime.now().timestamp() + 300)
        
        return result
    
    def get_category_stats(self):
        """Статистика по категориям"""
        return {
            'total_categories_tracked': len(request_stats),
            'categories': request_stats,
            'problematic_categories': [
                cat for cat, stats in request_stats.items() 
                if stats.get('failures', 0) > stats.get('success', 0)
            ]
        }


client = OCSClient()


# ============ РУЧКИ API ============

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS API Proxy',
        'status': 'operational',
        'version': '2.1-no-limits',
        'features': [
            '✅ No artificial limits on categories/products',
            'Retry mechanism for failed requests',
            'Smart caching (configurable TTL)',
            'Pagination support with per_page up to 500',
            'Category statistics and monitoring'
        ],
        'endpoints': {
            'cities': '/api/cities',
            'categories': '/api/categories',
            'categories_light': '/api/categories/light',
            'products': '/api/categories/<category>/products?shipmentcity=...',
            'products_paginated': '/api/categories/<category>/products/page/<int:page>?shipmentcity=...&per_page=...',
            'product_info': '/api/products/<item_id>?shipmentcity=...',
            'currency': '/api/currency',
            'stats': '/api/stats',
            'health': '/api/health'
        },
        'tips': [
            'Use withdescriptions=false for faster product requests',
            'Use pagination for large result sets',
            'Client-side caching recommended for production'
        ]
    })


@app.route('/api/cities')
def get_cities():
    result = client.get_shipment_cities()
    return jsonify(result)


@app.route('/api/categories')
def get_categories():
    """Полное дерево категорий"""
    result = client.get_categories_tree()
    return jsonify(result)


@app.route('/api/categories/light')
def get_categories_light():
    """Основные категории — БЕЗ лимита"""
    result = client.get_categories_light()
    return jsonify(result)


@app.route('/api/categories/<category>/products')
def get_category_products(category):
    """Товары по категории — БЕЗ лимита"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': 'false',
        'includeuncondition': 'false',
        'includemissing': 'false',
        'withdescriptions': request.args.get('withdescriptions', 'false'),
    }
    
    for param in ['locations', 'producers', 'includesale', 'includeuncondition', 'includemissing']:
        if param in request.args:
            params[param] = request.args.get(param)
    
    result = client.get_products_by_category(category, shipmentcity, **params)
    return jsonify(result)


@app.route('/api/categories/<category>/products/page/<int:page>')
def get_category_products_paginated(category, page):
    """Товары с пагинацией — per_page до 500"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    # ✅ УВЕЛИЧЕНО: per_page до 500 (было 100)
    per_page = int(request.args.get('per_page', 100))
    if per_page > 500:
        per_page = 500
        logger.warning(f"per_page limited to 500 for performance")
    
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'withdescriptions': request.args.get('withdescriptions', 'false'),
    }
    
    result = client.get_products_paginated(category, shipmentcity, page, per_page, **params)
    return jsonify(result)


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


@app.route('/api/currency')
def get_currency():
    result = client.get_currency_exchanges()
    return jsonify(result)


@app.route('/api/stats')
def get_stats():
    stats = client.get_category_stats()
    cache_info = {
        'total_entries': len(cache),
        'keys': list(cache.keys())[:20]
    }
    
    return jsonify({
        'request_statistics': stats,
        'cache_info': cache_info,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/health')
def health():
    cities = client.get_shipment_cities()
    currency = client.get_currency_exchanges()
    
    health_status = 'healthy'
    checks = {
        'cities_endpoint': 'ok' if 'error' not in cities else 'failed',
        'currency_endpoint': 'ok' if 'error' not in currency else 'failed',
        'cache': 'ok' if len(cache) > 0 else 'empty'
    }
    
    if 'failed' in checks.values():
        health_status = 'degraded'
    
    problematic = [
        cat for cat, stats in request_stats.items()
        if stats.get('failures', 0) > 2 and stats.get('success', 0) == 0
    ]
    
    total_req = sum(s.get('total', 0) for s in request_stats.values())
    total_ok = sum(s.get('success', 0) for s in request_stats.values())
    
    return jsonify({
        'status': health_status,
        'checks': checks,
        'problematic_categories': problematic[:5],
        'timestamp': datetime.now().isoformat(),
        'uptime_checks': {
            'total_requests': total_req,
            'success_rate': f"{total_ok / max(1, total_req):.1%}"
        }
    })


@app.route('/api/cache/clear', methods=['POST', 'GET'])
def clear_cache():
    """Очистка кэша"""
    cleared = len(cache)
    cache.clear()
    return jsonify({
        'message': 'Cache cleared',
        'cleared_entries': cleared,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/tips')
def get_tips():
    return jsonify({
        'performance_tips': [
            'Use ?withdescriptions=false for 2-3x faster product requests',
            'Use pagination for large categories: ?page=1&per_page=100',
            'Cache responses client-side (localStorage/IndexedDB)',
            'Request only needed fields via API parameters'
        ],
        'recommended_flow': [
            '1. GET /api/cities',
            '2. GET /api/categories/light',
            '3. GET /api/categories/{code}/products?shipmentcity=...&withdescriptions=false',
            '4. GET /api/products/{id}?shipmentcity=... for details'
        ]
    })


@app.route('/api/test/category/<category>')
def test_category(category):
    """Тестирование конкретной категории"""
    shipmentcity = request.args.get('shipmentcity', 'Краснодар')
    
    start_time = time.time()
    result = client.get_products_by_category(category, shipmentcity, withdescriptions='false')
    elapsed = time.time() - start_time
    
    response = {
        'category': category,
        'shipmentcity': shipmentcity,
        'response_time': f"{elapsed:.2f}s",
        'result': 'success' if 'error' not in result else 'failed',
        'details': result if 'error' in result else {
            'products_count': len(result.get('result', [])),
            'note': 'No artificial limits applied'
        }
    }
    
    return jsonify(response)


# Редирект старых URL
@app.route('/content/<path:path>')
@app.route('/catalog/<path:path>')
@app.route('/logistic/<path:path>')
def old_urls_redirect(path):
    return jsonify({
        'error': 'Endpoint moved',
        'new_location': '/api/...',
        'documentation': '/',
        'timestamp': datetime.now().isoformat()
    }), 404


if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        threaded=True
    )
