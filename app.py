import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from functools import wraps
import time

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Конфигурация для Render
API_KEY = os.getenv('OCS_API_KEY', os.getenv('OCS_API_KEY'))
BASE_URL = 'https://connector.b2b.ocs.ru/api/v2'

# Кэширование для ускорения запросов (простая реализация)
cache = {}

def cache_response(timeout=300):
    """Декоратор для кэширования ответов"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cache_key = f"{request.path}?{request.query_string.decode()}"
            
            # Проверяем кэш
            if cache_key in cache:
                cached_data, timestamp = cache[cache_key]
                if time.time() - timestamp < timeout:
                    logger.info(f"Cache hit for {cache_key}")
                    return jsonify(cached_data)
            
            # Выполняем функцию
            result = f(*args, **kwargs)
            
            # Кэшируем результат
            if result and hasattr(result, 'json') and callable(result.json):
                response_data = result.json
                if callable(response_data):
                    response_data = response_data()
                cache[cache_key] = (response_data, time.time())
            
            return result
        return decorated_function
    return decorator

class OCSClient:
    def __init__(self):
        self.session = requests.Session()
        if API_KEY:
            self.session.headers.update({
                'accept': 'application/json',
                'X-API-Key': API_KEY,
                'User-Agent': 'OCS-API-Render/1.0'
            })
        # Убраны таймауты для Render - используем настройки gunicorn
        self.timeout = None
    
    def get_categories(self, use_cache=True):
        """Получение категорий с кэшированием"""
        if not API_KEY:
            return {'error': 'API key not configured', 'categories': []}
        
        cache_key = 'categories'
        if use_cache and cache_key in cache:
            cached_data, timestamp = cache[cache_key]
            if time.time() - timestamp < 300:  # 5 минут кэш
                logger.info("Returning cached categories")
                return cached_data
        
        try:
            logger.info(f"Fetching categories from {BASE_URL}/catalog/categories")
            response = self.session.get(
                f'{BASE_URL}/catalog/categories',
                timeout=self.timeout  # Без таймаута для Render
            )
            response.raise_for_status()
            data = response.json()
            
            # Кэшируем результат
            cache[cache_key] = (data, time.time())
            logger.info(f"Successfully fetched {len(data.get('categories', []))} categories")
            return data
        except requests.exceptions.Timeout:
            logger.error("Request timeout")
            return {'error': 'Request timeout', 'categories': []}
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {str(e)}")
            return {'error': str(e), 'categories': []}
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {'error': str(e), 'categories': []}

client = OCSClient()

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS API Proxy',
        'version': '1.0',
        'status': 'active',
        'endpoints': {
            'categories': '/categories',
            'health': '/health',
            'cache_info': '/cache-info',
            'test': '/test'
        },
        'environment': os.getenv('RENDER', 'local')
    })

@app.route('/categories')
@cache_response(timeout=300)  # Кэшируем на 5 минут
def get_categories():
    """Получение списка категорий"""
    return jsonify(client.get_categories())

@app.route('/health')
def health():
    """Health check для Render"""
    try:
        # Быстрая проверка без обращения к внешнему API
        return jsonify({
            'status': 'healthy',
            'timestamp': time.time(),
            'environment': os.getenv('RENDER', 'local')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/test')
def test():
    """Тестовый эндпоинт"""
    return jsonify({
        'message': 'API is working correctly',
        'server_time': time.time(),
        'api_key_configured': bool(API_KEY),
        'environment': os.getenv('RENDER', 'local')
    })

@app.route('/cache-info')
def cache_info():
    """Информация о кэше"""
    return jsonify({
        'cache_size': len(cache),
        'cache_keys': list(cache.keys()),
        'timestamp': time.time()
    })

@app.route('/clear-cache')
def clear_cache():
    """Очистка кэша"""
    cache.clear()
    return jsonify({
        'message': 'Cache cleared',
        'timestamp': time.time()
    })

# Обработчики ошибок
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

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
        threaded=True  # Включаем многопоточность
    )