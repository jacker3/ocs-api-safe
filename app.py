import os
import requests
import logging
import time
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import functools
import signal
import threading

load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Обработчик сигнала для graceful shutdown
def signal_handler(signum, frame):
    logger.info("Received shutdown signal")
    os._exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

app = Flask(__name__)
CORS(app)

# Простой кэш в памяти с TTL
cache = {}
cache_lock = threading.RLock()

class ThreadSafeCache:
    """Потокобезопасный кэш"""
    
    @staticmethod
    def get(key):
        with cache_lock:
            if key in cache:
                data, timestamp, ttl = cache[key]
                if datetime.now() - timestamp < timedelta(seconds=ttl):
                    return data
                else:
                    del cache[key]
            return None
    
    @staticmethod
    def set(key, data, ttl=300):
        with cache_lock:
            cache[key] = (data, datetime.now(), ttl)
    
    @staticmethod
    def clear():
        with cache_lock:
            cache.clear()
    
    @staticmethod
    def size():
        with cache_lock:
            return len(cache)

def cache_response(ttl_seconds=300):
    """Декоратор для кэширования ответов"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Проверяем кэш
            cached = ThreadSafeCache.get(cache_key)
            if cached is not None:
                logger.info(f"Cache hit for {cache_key}")
                return cached
            
            # Выполняем функцию
            result = func(*args, **kwargs)
            
            # Сохраняем в кэш только успешные результаты
            if result and not isinstance(result, dict) or "error" not in result:
                ThreadSafeCache.set(cache_key, result, ttl_seconds)
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
    """Класс для работы с OCS API с оптимизациями"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Можно использовать тестовый URL если задан
        self.base_url = os.getenv('OCS_API_URL', 'https://connector.b2b.ocs.ru/api/v2')
        
        # Создаем отдельные сессии для разных типов запросов
        self.fast_session = self._create_session(timeout=(10, 30))
        self.slow_session = self._create_session(timeout=(60, 300))  # 5 минут для медленных запросов
        
        logger.info(f"OCS API initialized with URL: {self.base_url}")
    
    def _create_session(self, timeout=(30, 60)):
        """Создание сессии с настройками"""
        session = requests.Session()
        session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': 'OCS-Integration/2.0'
        })
        
        # Настройки адаптера
        adapter = requests.adapters.HTTPAdapter(
            max_retries=2,
            pool_connections=10,
            pool_maxsize=10,
            pool_block=False
        )
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        
        # Сохраняем таймаут в сессии
        session.timeout = timeout
        return session
    
    def _make_request_with_timeout(self, endpoint, params=None, method='GET', data=None, timeout=None):
        """Выполнение запроса с контролем таймаута"""
        url = f"{self.base_url}/{endpoint}"
        logger.info(f"OCS API: {method} {url}")
        
        # Выбираем сессию в зависимости от типа запроса
        if 'catalog/categories' in endpoint:
            session = self.slow_session
            if timeout is None:
                timeout = (60, 300)  # 5 минут для категорий
        else:
            session = self.fast_session
            if timeout is None:
                timeout = (30, 120)  # 2 минуты для остального
        
        start_time = time.time()
        
        try:
            if method == 'GET':
                response = session.get(url, params=params, timeout=timeout, verify=True)
            elif method == 'POST':
                response = session.post(url, params=params, json=data, timeout=timeout, verify=True)
            elif method == 'PUT':
                response = session.put(url, params=params, json=data, timeout=timeout, verify=True)
            elif method == 'DELETE':
                response = session.delete(url, params=params, timeout=timeout, verify=True)
            else:
                return {"error": f"Unsupported method: {method}", "code": 400}
            
            elapsed = time.time() - start_time
            logger.info(f"OCS Response: {response.status_code} in {elapsed:.2f}s")
            
            if response.status_code == 200:
                try:
                    return response.json()
                except json.JSONDecodeError as e:
                    logger.error(f"JSON error: {e}")
                    return {"error": "Invalid JSON", "code": 500}
            else:
                return {"error": f"HTTP {response.status_code}", "code": response.status_code}
                
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            logger.error(f"Timeout after {elapsed:.2f}s")
            return {"error": "Request timeout", "code": 408}
        except Exception as e:
            logger.error(f"Request error: {str(e)}")
            return {"error": str(e), "code": 500}
    
    # ===== ОПТИМИЗИРОВАННЫЕ МЕТОДЫ =====
    
    @cache_response(ttl_seconds=3600)  # 1 час
    def get_categories_simple(self):
        """Упрощенный запрос категорий - только первый уровень"""
        # Пытаемся получить минимальные данные
        return self._make_request_with_timeout(
            "catalog/categories",
            timeout=(30, 60)  # 1 минута максимум
        )
    
    @cache_response(ttl_seconds=3600)
    def get_categories_full(self):
        """Полный запрос категорий (может быть медленным)"""
        return self._make_request_with_timeout(
            "catalog/categories",
            timeout=(120, 600)  # 10 минут максимум
        )
    
    @cache_response(ttl_seconds=1800)
    def get_shipment_cities(self):
        """Города отгрузки"""
        return self._make_request_with_timeout(
            "logistic/shipment/cities",
            timeout=(10, 30)
        )
    
    def get_products_by_category(self, category, shipment_city, **params):
        """Товары по категории"""
        endpoint = f"catalog/categories/{category}/products"
        all_params = {'shipmentcity': shipment_city, **params}
        return self._make_request_with_timeout(
            endpoint,
            params=all_params,
            timeout=(30, 180)
        )

# Инициализация API
api_key = os.getenv('OCS_API_KEY')
if not api_key:
    logger.warning("OCS_API_KEY not found")
    ocs_api = None
else:
    logger.info("OCS API initialized")
    ocs_api = OCSAPI(api_key=api_key)

# ===== ПРЕДВАРИТЕЛЬНОЕ КЭШИРОВАНИЕ В ФОНОВОМ РЕЖИМЕ =====

def preload_cache():
    """Предварительная загрузка кэша в фоновом режиме"""
    if not ocs_api:
        return
    
    logger.info("Starting cache preload")
    
    try:
        # Загружаем города (быстро)
        cities = ocs_api.get_shipment_cities()
        if cities and "error" not in cities:
            logger.info(f"Preloaded {len(cities) if isinstance(cities, list) else 1} cities")
    except Exception as e:
        logger.error(f"Failed to preload cities: {e}")
    
    # Категории загружаем только если есть время
    # (это может занять много времени)

# Запускаем предзагрузку в фоновом потоке
preload_thread = threading.Thread(target=preload_cache, daemon=True)
preload_thread.start()

# ===== УПРОЩЕННЫЕ ЭНДПОИНТЫ =====

@app.route('/')
def home():
    return jsonify({
        "service": "OCS B2B API Proxy",
        "version": "2.1.0",
        "status": "ready",
        "ocs_api": "configured" if ocs_api else "not_configured",
        "cache_size": ThreadSafeCache.size(),
        "endpoints": [
            "/api/v2/health",
            "/api/v2/cities",
            "/api/v2/categories",
            "/api/v2/categories/simple",
            "/api/v2/categories/debug"
        ],
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/health')
def health_check():
    """Быстрая проверка здоровья"""
    return jsonify({
        "status": "healthy",
        "ocs_api": bool(ocs_api),
        "cache_items": ThreadSafeCache.size(),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/cities')
def get_cities():
    """Города отгрузки - всегда быстрый запрос"""
    if not ocs_api:
        return jsonify({"error": "API not configured"}), 500
    
    try:
        result = ocs_api.get_shipment_cities()
        
        if result and "error" not in result:
            return jsonify({
                "success": True,
                "data": result,
                "cached": True,
                "count": len(result) if isinstance(result, list) else 1
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error") if result else "No response"
            }), result.get("code", 500) if result else 500
            
    except Exception as e:
        logger.error(f"Cities error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/v2/categories/simple')
def get_categories_simple():
    """Упрощенные категории (быстрее)"""
    if not ocs_api:
        return jsonify({"error": "API not configured"}), 500
    
    # Устанавливаем таймаут для всего запроса Flask
    request.environ['REQUEST_TIMEOUT'] = 60  # 1 минута
    
    try:
        logger.info("Getting simplified categories")
        result = ocs_api.get_categories_simple()
        
        if result and "error" not in result:
            # Упрощаем структуру для более быстрого ответа
            if isinstance(result, list):
                simplified = []
                for item in result[:50]:  # Ограничиваем количество
                    if isinstance(item, dict):
                        simplified.append({
                            'id': item.get('category'),
                            'name': item.get('name'),
                            'children_count': len(item.get('children', [])) if isinstance(item.get('children'), list) else 0
                        })
                result = simplified
            
            return jsonify({
                "success": True,
                "data": result,
                "cached": True,
                "note": "Simplified structure for faster response",
                "count": len(result) if isinstance(result, list) else 0
            })
        else:
            return handle_ocs_error(result)
            
    except Exception as e:
        logger.error(f"Categories error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/v2/categories')
def get_categories():
    """Полные категории (может быть медленно)"""
    if not ocs_api:
        return jsonify({"error": "API not configured"}), 500
    
    # Проверяем, есть ли в кэше
    cache_key = "categories_full_cached"
    cached = ThreadSafeCache.get(cache_key)
    if cached:
        logger.info("Returning cached full categories")
        return jsonify({
            "success": True,
            "data": cached,
            "cached": True,
            "from_cache": True
        })
    
    # Если нет в кэше, пробуем загрузить с таймаутом
    request.environ['REQUEST_TIMEOUT'] = 300  # 5 минут
    
    try:
        logger.info("Fetching full categories from OCS")
        result = ocs_api.get_categories_full()
        
        if result and "error" not in result:
            # Сохраняем в кэш
            ThreadSafeCache.set(cache_key, result, 3600)  # 1 час
            
            return jsonify({
                "success": True,
                "data": result,
                "cached": True,
                "count": len(result) if isinstance(result, list) else 0,
                "note": "Full categories loaded from OCS"
            })
        else:
            return handle_ocs_error(result)
            
    except Exception as e:
        logger.error(f"Full categories error: {e}")
        # Пробуем вернуть упрощенные категории как fallback
        return get_categories_simple()

@app.route('/api/v2/categories/debug')
def get_categories_debug():
    """Отладочная информация о категориях"""
    if not ocs_api:
        return jsonify({"error": "API not configured"}), 500
    
    # Быстрый ответ с метаданными
    cache_key = "categories_metadata"
    cached = ThreadSafeCache.get(cache_key)
    
    if cached:
        return jsonify({
            "success": True,
            "metadata": cached,
            "cached": True
        })
    
    # Пытаемся получить небольшой кусочек данных для анализа
    try:
        # Делаем быстрый запрос с таймаутом
        result = ocs_api._make_request_with_timeout(
            "catalog/categories",
            timeout=(10, 30)  # 30 секунд максимум
        )
        
        metadata = {
            "available": bool(result and "error" not in result),
            "is_list": isinstance(result, list),
            "estimated_size": len(json.dumps(result)) if result else 0,
            "sample_count": len(result[:5]) if isinstance(result, list) and result else 0,
            "sample": result[:2] if isinstance(result, list) and len(result) > 2 else result,
            "has_children": False
        }
        
        if isinstance(result, list) and result:
            first_item = result[0]
            if isinstance(first_item, dict):
                metadata["has_children"] = bool(first_item.get('children'))
                metadata["structure"] = list(first_item.keys())
        
        ThreadSafeCache.set(cache_key, metadata, 300)  # 5 минут
        
        return jsonify({
            "success": True,
            "metadata": metadata,
            "recommendation": "Use /api/v2/categories/simple for faster response",
            "warning": "Full categories may take several minutes to load"
        })
        
    except Exception as e:
        logger.error(f"Debug error: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "recommendation": "Check OCS API availability"
        }), 500

def handle_ocs_error(result):
    """Обработка ошибок OCS API"""
    if not result:
        return jsonify({"error": "No response from OCS API"}), 500
    
    error_msg = result.get("error", "Unknown error")
    error_code = result.get("code", 500)
    
    # Специальная обработка таймаутов
    if error_code == 408:
        return jsonify({
            "error": "OCS API timeout - server is too slow",
            "suggestion": "Try simplified endpoint: /api/v2/categories/simple",
            "ocs_error": error_msg,
            "code": 408
        }), 408
    
    return jsonify({
        "error": f"OCS API error: {error_msg}",
        "ocs_error": error_msg,
        "code": error_code
    }), error_code

# ===== ОСТАЛЬНЫЕ ЭНДПОИНТЫ (оптимизированные) =====

@app.route('/api/v2/catalog/categories/<category>/products')
def get_category_products(category):
    if not ocs_api:
        return jsonify({"error": "API not configured"}), 500
    
    shipment_city = request.args.get('shipmentcity', 'Москва')
    
    # Нормализация
    if category in ['all', 'undefined', '']:
        category = 'all'
    
    # Устанавливаем разумный таймаут
    request.environ['REQUEST_TIMEOUT'] = 180  # 3 минуты
    
    try:
        params = request.args.to_dict()
        if 'shipmentcity' in params:
            shipment_city = params.pop('shipmentcity')
        
        result = ocs_api.get_products_by_category(category, shipment_city, **params)
        
        if result and "error" not in result:
            products = result.get('result', [])
            return jsonify({
                "success": True,
                "category": category,
                "city": shipment_city,
                "product_count": len(products),
                "data": {
                    "products": products[:100],  # Ограничиваем для быстрого ответа
                    "has_more": len(products) > 100
                },
                "total_available": len(products)
            })
        else:
            return handle_ocs_error(result)
            
    except Exception as e:
        logger.error(f"Products error: {e}")
        return jsonify({"error": str(e)}), 500

# ===== УТИЛИТЫ =====

@app.route('/api/v2/debug/cache')
def debug_cache():
    """Информация о кэше"""
    cache_data = []
    
    # Только ключи, без значений (чтобы не перегружать)
    with cache_lock:
        for key, (value, timestamp, ttl) in list(cache.items())[:20]:  # Первые 20
            age = datetime.now() - timestamp
            cache_data.append({
                "key": key[:80] + "..." if len(key) > 80 else key,
                "age_seconds": int(age.total_seconds()),
                "ttl_seconds": ttl,
                "type": type(value).__name__
            })
    
    return jsonify({
        "cache_size": ThreadSafeCache.size(),
        "cache_entries": cache_data,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/debug/clear-cache')
def clear_cache():
    """Очистка кэша"""
    old_size = ThreadSafeCache.size()
    ThreadSafeCache.clear()
    
    return jsonify({
        "success": True,
        "cleared": old_size,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/debug/status')
def debug_status():
    """Расширенный статус"""
    return jsonify({
        "service": "OCS API Proxy",
        "status": "running",
        "ocs_api": {
            "configured": bool(ocs_api),
            "url": ocs_api.base_url if ocs_api else None
        },
        "cache": {
            "size": ThreadSafeCache.size(),
            "preload_thread": preload_thread.is_alive()
        },
        "timestamp": datetime.now().isoformat(),
        "gunicorn_timeout_note": "Set timeout=300 in gunicorn config"
    })

# ===== ЗАПУСК С WAITRESS (рекомендуется) =====

def run_with_waitress():
    """Запуск с Waitress (лучше для длинных запросов)"""
    from waitress import serve
    
    logger.info("Starting with Waitress (better for long requests)")
    logger.info(f"Cache size: {ThreadSafeCache.size()}")
    
    # Waitress лучше справляется с длинными запросами
    serve(
        app,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 10000)),
        threads=100,  # Много потоков для параллельных запросов
        connection_limit=1000,
        channel_timeout=300,  # 5 минут
        cleanup_interval=30
    )

def run_with_flask():
    """Запуск с Flask development server"""
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting with Flask on port {port}")
    
    # Flask dev server с увеличенными настройками
    app.run(
        host='0.0.0.0',
        port=port,
        debug=os.environ.get('FLASK_ENV') == 'development',
        threaded=True,
        processes=1
    )

if __name__ == '__main__':
    # Выбираем сервер в зависимости от окружения
    if os.environ.get('USE_WAITRESS', 'true').lower() == 'true':
        run_with_waitress()
    else:
        run_with_flask()