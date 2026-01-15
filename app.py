import os
import requests
import json
import threading
import time
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS
import atexit

app = Flask(__name__)
CORS(app)

# Конфигурация
API_KEY = os.getenv('OCS_API_KEY')
BASE_URL = 'https://connector.b2b.ocs.ru/api/v2'

# Кеш категорий в памяти
categories_cache = {
    'data': {'categories': [], 'error': 'Initializing...'},
    'last_update': None,
    'is_updating': False,
    'last_error': None
}

class OCSClient:
    def __init__(self):
        self.session = None
        if API_KEY:
            self.session = requests.Session()
            self.session.headers.update({
                'accept': 'application/json',
                'X-API-Key': API_KEY,
            })
            # Короткий таймаут для фоновых задач
            self.timeout = (10, 30)
    
    def get_categories_safe(self):
        """Безопасное получение категорий с коротким таймаутом"""
        if not self.session:
            return {'error': 'API key not configured', 'categories': []}
        
        url = f'{BASE_URL}/catalog/categories'
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            return {'error': 'OCS API timeout (30s)', 'categories': []}
        except requests.exceptions.RequestException as e:
            return {'error': f'Request failed: {str(e)}', 'categories': []}
        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}', 'categories': []}

# Инициализация клиента
client = OCSClient() if API_KEY else None

def update_categories_background():
    """Фоновая задача для обновления категорий"""
    if not client:
        return
    
    categories_cache['is_updating'] = True
    try:
        result = client.get_categories_safe()
        categories_cache['data'] = result
        categories_cache['last_update'] = datetime.now()
        categories_cache['last_error'] = result.get('error')
        app.logger.info(f"Categories updated at {datetime.now()}")
    except Exception as e:
        categories_cache['last_error'] = str(e)
        app.logger.error(f"Failed to update categories: {str(e)}")
    finally:
        categories_cache['is_updating'] = False

def start_background_updater():
    """Запускает фоновое обновление категорий"""
    if not API_KEY:
        return
    
    # Первое обновление
    update_categories_background()
    
    # Запускаем периодическое обновление каждые 5 минут
    def updater():
        while True:
            time.sleep(300)  # 5 минут
            if not categories_cache['is_updating']:
                update_categories_background()
    
    thread = threading.Thread(target=updater, daemon=True)
    thread.start()
    return thread

# Запускаем фоновое обновление при старте
background_thread = None

@app.before_first_request
def initialize():
    global background_thread
    if API_KEY:
        background_thread = start_background_updater()

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS Categories API',
        'endpoints': ['/categories', '/health', '/status'],
        'api_key_configured': bool(API_KEY),
        'cached': True,
        'note': 'Categories are cached and updated in background'
    })

@app.route('/categories')
def get_categories():
    """Возвращает кешированные категории"""
    return jsonify(categories_cache['data'])

@app.route('/health')
def health():
    """Проверка здоровья - всегда быстрая"""
    return jsonify({
        'status': 'ok',
        'api_configured': bool(API_KEY),
        'cached_data_available': categories_cache['last_update'] is not None
    })

@app.route('/status')
def status():
    """Статус обновления категорий"""
    return jsonify({
        'last_update': categories_cache['last_update'].isoformat() if categories_cache['last_update'] else None,
        'is_updating': categories_cache['is_updating'],
        'last_error': categories_cache['last_error'],
        'api_configured': bool(API_KEY)
    })

@app.route('/force-update')
def force_update():
    """Принудительное обновление категорий (только если не обновляется)"""
    if not API_KEY:
        return jsonify({'error': 'API key not configured'}), 400
    
    if categories_cache['is_updating']:
        return jsonify({'error': 'Update already in progress'}), 429
    
    # Запускаем обновление в отдельном потоке
    thread = threading.Thread(target=update_categories_background, daemon=True)
    thread.start()
    
    return jsonify({
        'message': 'Update started in background',
        'started_at': datetime.now().isoformat()
    })

@app.route('/test-simple')
def test_simple():
    """Простой тестовый эндпоинт с фиксированными данными"""
    return jsonify({
        'test': 'success',
        'categories': [
            {'category': 'TEST1', 'name': 'Test Category 1', 'children': []},
            {'category': 'TEST2', 'name': 'Test Category 2', 'children': []}
        ],
        'timestamp': datetime.now().isoformat()
    })

# Обработчик выхода
atexit.register(lambda: app.logger.info("Shutting down..."))

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    
    # Инициализация при старте
    if API_KEY:
        background_thread = start_background_updater()
    
    app.run(
        host='0.0.0.0', 
        port=port, 
        threaded=True,
        debug=False
    )