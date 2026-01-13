import os
import requests
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
    
    def get_categories(self):
        """Получение категорий без ограничений"""
        url = f'{BASE_URL}/catalog/categories'
        try:
            response = self.session.get(url)
            return response.json()
        except Exception as e:
            return {'error': str(e)}

# Инициализация клиента
client = OCSClient() if API_KEY else None

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS Categories API',
        'endpoints': ['/categories'],
        'api_key_configured': bool(API_KEY)
    })

@app.route('/categories')
def get_categories():
    if not client:
        return jsonify({'error': 'API key not configured'}), 500
    
    result = client.get_categories()
    
    if 'error' in result:
        return jsonify(result), 500
    
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port)