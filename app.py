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
