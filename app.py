import os
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
BASE_URL = 'https://connector.b2b.ocs.ru/api/v2'

# Кэш с TTL
cache = {}
CACHE_TTL = 300  # 5 минут

# Статистика запросов для мониторинга проблемных категорий
request_stats = {}

def log_statistics(category, success, response_time):
    """Логируем статистику по запросам"""
    if category not in request_stats:
        request_stats[category] = {
            'total': 0,
            'success': 0,
            'failures': 0,
            'avg_time': 0,
            'last_times': []
        }
    
    stats = request_stats[category]
    stats['total'] += 1
    
    if success:
        stats['success'] += 1
        # Храним последние 10 успешных времен
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
                'User-Agent': 'OCS-API/1.0'
            })
    
    def _make_request_with_retry(self, method, endpoint, params=None, data=None, 
                               max_retries=2, timeout=(5, 15)):
        """Запрос с ретраями для проблемных категорий"""
        for attempt in range(max_retries + 1):
            try:
                url = f"{BASE_URL}{endpoint}"
                
                # Для повторных попыток добавляем небольшую задержку
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
        
        # Проверяем кэш
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"Cache hit for categories tree")
                return data
        
        result, elapsed, success = self._make_request_with_retry(
            'GET', '/catalog/categories',
            max_retries=max_retries,
            timeout=(5, 20)  # Увеличиваем таймаут для дерева
        )
        
        log_statistics('categories_tree', success, elapsed)
        
        if success:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_categories_light(self):
        """Легкая версия - только основные категории без дерева"""
        cache_key = 'categories_light'
        
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                return data
        
        # Пробуем получить дерево
        tree = self.get_categories_tree()
        
        if 'error' in tree:
            # Если не получается дерево, возвращаем статичный список основных категорий
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
        
        # Извлекаем только основные категории (первый уровень)
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
        result = {'categories': main_cats[:20]}  # Ограничиваем 20 категориями
        
        cache[cache_key] = (result, datetime.now().timestamp())
        return result
    
    def get_products_by_category(self, category, shipmentcity, **params):
        """Товары по категории с оптимизациями"""
        cache_key = f"products_{category}_{shipmentcity}_{str(params)}"
        
        # Проверяем кэш
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < CACHE_TTL:
                logger.info(f"Cache hit for category {category}")
                return data
        
        # Проблемные категории получаем с ретраями
        max_retries = 2 if category in ['V08', 'V09', 'V02'] else 1
        
        endpoint = f"/catalog/categories/{category}/products"
        query_params = {'shipmentcity': shipmentcity}
        query_params.update(params)
        
        # ОПТИМИЗАЦИЯ: Отключаем описания для ускорения
        if 'withdescriptions' not in query_params:
            query_params['withdescriptions'] = 'false'
        
        # ОПТИМИЗАЦИЯ: Ограничиваем количество возвращаемых товаров
        if 'limit' not in query_params and 'top' not in query_params:
            # Не добавляем лимит в запрос, но логируем
            logger.info(f"Requesting category {category} without limit")
        
        result, elapsed, success = self._make_request_with_retry(
            'GET', endpoint,
            params=query_params,
            max_retries=max_retries,
            timeout=(5, 20) if category in ['V08', 'V09', 'V02'] else (5, 15)
        )
        
        log_statistics(category, success, elapsed)
        
        if success and isinstance(result, dict):
            # Ограничиваем количество товаров в ответе для тяжелых категорий
            if 'result' in result and isinstance(result['result'], list):
                if len(result['result']) > 100 and category in ['V08', 'V09', 'V02']:
                    result['result'] = result['result'][:100]
                    result['warning'] = f'Limited to 100 products, total: {len(result["result"])}'
                    result['suggestion'] = 'Use pagination or filter by subcategories'
            
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_products_paginated(self, category, shipmentcity, page=1, per_page=50, **params):
        """Пагинация товаров по категории"""
        # В реальности API OCS не поддерживает пагинацию,
        # но мы можем эмулировать её на нашей стороне
        
        all_products = self.get_products_by_category(category, shipmentcity, **params)
        
        if 'error' in all_products:
            return all_products
        
        if 'result' not in all_products or not isinstance(all_products['result'], list):
            return {'error': 'Invalid response format', 'data': all_products}
        
        products = all_products['result']
        total = len(products)
        
        # Вычисляем индексы для пагинации
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        if start_idx >= total:
            return {
                'result': [],
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'total_pages': (total + per_page - 1) // per_page,
                    'has_next': False,
                    'has_prev': page > 1
                }
            }
        
        paginated_products = products[start_idx:end_idx]
        
        return {
            'result': paginated_products,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page,
                'has_next': end_idx < total,
                'has_prev': page > 1
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
            'GET', endpoint,
            params=query_params,
            timeout=(3, 10)
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
            'GET', '/logistic/shipment/cities',
            timeout=(3, 10)
        )
        
        if success:
            cache[cache_key] = (result, datetime.now().timestamp())
        
        return result
    
    def get_currency_exchanges(self):
        """Курсы валют"""
        cache_key = 'currency_exchanges'
        
        # Кэшируем на 5 минут
        if cache_key in cache:
            data, timestamp = cache[cache_key]
            if datetime.now().timestamp() - timestamp < 300:  # 5 минут
                return data
        
        result, elapsed, success = self._make_request_with_retry(
            'GET', '/account/currencies/exchanges',
            timeout=(3, 10)
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
        'version': '2.0',
        'features': [
            'Retry mechanism for failed requests',
            'Smart caching (5 minutes TTL)',
            'Pagination support',
            'Category statistics',
            'Optimized timeouts'
        ],
        'endpoints': {
            'cities': '/api/cities',
            'categories': '/api/categories',
            'categories_light': '/api/categories/light',
            'products': '/api/categories/<category>/products?shipmentcity=...',
            'products_paginated': '/api/categories/<category>/products/page/<int:page>?shipmentcity=...',
            'product_info': '/api/products/<item_id>?shipmentcity=...',
            'currency': '/api/currency',
            'stats': '/api/stats',
            'health': '/api/health'
        },
        'tips': [
            'Use /api/categories/light for faster category list',
            'Problematic categories (V08, V09, V02) have automatic retries',
            'Add withdescriptions=false to speed up product requests',
            'Use pagination for categories with many products'
        ]
    })

@app.route('/api/cities')
def get_cities():
    """Города отгрузки"""
    result = client.get_shipment_cities()
    return jsonify(result)

@app.route('/api/categories')
def get_categories():
    """Полное дерево категорий (может быть медленным)"""
    result = client.get_categories_tree()
    return jsonify(result)

@app.route('/api/categories/light')
def get_categories_light():
    """Легкий список основных категорий"""
    result = client.get_categories_light()
    return jsonify(result)

@app.route('/api/categories/<category>/products')
def get_category_products(category):
    """Товары по категории"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    # Параметры для оптимизации
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': 'false',
        'includeuncondition': 'false',
        'includemissing': 'false',
        'withdescriptions': request.args.get('withdescriptions', 'false'),  # По умолчанию false для скорости
    }
    
    # Дополнительные параметры
    for param in ['locations', 'producers', 'includesale', 'includeuncondition', 'includemissing']:
        if param in request.args:
            params[param] = request.args.get(param)
    
    # Проверяем проблемные категории
    if category in ['V08', 'V09', 'V02']:
        params['warning'] = 'This category may be slow. Using retry mechanism.'
    
    result = client.get_products_by_category(category, shipmentcity, **params)
    return jsonify(result)

@app.route('/api/categories/<category>/products/page/<int:page>')
def get_category_products_paginated(category, page):
    """Товары по категории с пагинацией"""
    shipmentcity = request.args.get('shipmentcity')
    if not shipmentcity:
        return jsonify({'error': 'Parameter shipmentcity is required'}), 400
    
    per_page = int(request.args.get('per_page', 50))
    if per_page > 100:
        per_page = 100
    
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
    """Курсы валют"""
    result = client.get_currency_exchanges()
    return jsonify(result)

@app.route('/api/stats')
def get_stats():
    """Статистика запросов"""
    stats = client.get_category_stats()
    cache_info = {
        'total_entries': len(cache),
        'keys': list(cache.keys())[:10]
    }
    
    return jsonify({
        'request_statistics': stats,
        'cache_info': cache_info,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/health')
def health():
    """Health check с проверкой основных функций"""
    # Проверяем быстрые эндпоинты
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
    
    # Проверяем проблемные категории
    problematic = []
    for category, stats in request_stats.items():
        if stats.get('failures', 0) > 2 and stats.get('success', 0) == 0:
            problematic.append(category)
    
    return jsonify({
        'status': health_status,
        'checks': checks,
        'problematic_categories': problematic[:5],
        'timestamp': datetime.now().isoformat(),
        'uptime_checks': {
            'total_requests': sum(stats.get('total', 0) for stats in request_stats.values()),
            'success_rate': f"{sum(stats.get('success', 0) for stats in request_stats.values()) / max(1, sum(stats.get('total', 0) for stats in request_stats.values())):.1%}"
        }
    })

@app.route('/api/cache/clear')
def clear_cache():
    """Очистка кэша"""
    cache.clear()
    return jsonify({
        'message': 'Cache cleared',
        'cleared_entries': len(cache),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/tips')
def get_tips():
    """Советы по использованию API"""
    return jsonify({
        'performance_tips': [
            '1. Use /api/categories/light instead of /api/categories for faster loading',
            '2. Add ?withdescriptions=false to product requests for 2-3x speedup',
            '3. Use pagination for large categories: /api/categories/V01/products/page/1',
            '4. Cache responses on your client side (browser/local storage)',
            '5. Request only needed fields - avoid includesale/includeuncondition if not needed'
        ],
        'problem_categories': [
            'V08, V09, V02 - these categories are large and may timeout',
            'Use pagination or limit results for these categories'
        ],
        'recommended_flow': [
            '1. GET /api/cities - get available cities',
            '2. GET /api/categories/light - get main categories',
            '3. GET /api/categories/{code}/products?shipmentcity=...&withdescriptions=false',
            '4. For details: GET /api/products/{id}?shipmentcity=...'
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
            'has_more': len(result.get('result', [])) > 100
        }
    }
    
    return jsonify(response)

# Обработчик 404 для старых URL
@app.route('/content/<path:path>')
@app.route('/catalog/<path:path>')
@app.route('/logistic/<path:path>')
def old_urls_redirect(path):
    """Редирект старых URL на новые"""
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