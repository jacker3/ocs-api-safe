import os
import requests
import json
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Конфигурация
API_KEY = os.getenv('OCS_API_KEY')
BASE_URL = 'https://connector.b2b.ocs.ru/api/v2'

class OCSClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': API_KEY,
        })
        # Увеличиваем таймауты еще больше
        self.timeout = (120, 600)  # 120 сек на соединение, 600 на чтение (10 минут)
    
    def get_categories(self):
        """Получение категорий с увеличенными таймаутами"""
        url = f'{BASE_URL}/catalog/categories'
        try:
            # Используем более долгий таймаут
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            # Возвращаем структуру с ошибкой, но без падения
            return {'error': 'Request timeout - OCS API is too slow', 'categories': []}
        except requests.exceptions.RequestException as e:
            return {'error': f'Request failed: {str(e)}', 'categories': []}
        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}', 'categories': []}

# Инициализация клиента
client = OCSClient() if API_KEY else None

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS Categories API',
        'endpoints': ['/categories'],
        'api_key_configured': bool(API_KEY),
        'note': 'Categories endpoint may take several minutes to load. Please be patient.'
    })

@app.route('/categories')
def get_categories():
    if not client:
        return jsonify({'error': 'API key not configured', 'categories': []}), 500
    
    try:
        result = client.get_categories()
        
        if 'error' in result:
            app.logger.warning(f"OCS API error: {result['error']}")
            # Возвращаем ошибку, но с 200 статусом, чтобы не было 502
            return jsonify(result)
        
        return jsonify(result)
        
    except Exception as e:
        app.logger.error(f"Unexpected error in /categories: {str(e)}")
        return jsonify({'error': f'Internal server error: {str(e)}', 'categories': []}), 500

@app.route('/health')
def health():
    """Простая проверка здоровья - всегда быстрая"""
    return jsonify({'status': 'ok', 'api_configured': bool(API_KEY)})

@app.route('/test')
def test():
    """Тестовый эндпоинт для проверки работы без таймаута"""
    return jsonify({
        'status': 'ok',
        'message': 'Service is running',
        'timestamp': '2026-01-15T06:00:00Z'
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    # Для локальной разработки с очень большими таймаутами
    app.run(
        host='0.0.0.0', 
        port=port, 
        threaded=True,
        # Эти параметры помогут на Render
        debug=False
    )