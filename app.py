import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Конфигурация
API_KEY = os.getenv('OCS_API_KEY')
BASE_URL = 'https://connector.b2b.ocs.ru/api/v2'

class OCSClient:
    def __init__(self):
        self.session = requests.Session() if API_KEY else None
        if self.session:
            self.session.headers.update({
                'accept': 'application/json',
                'X-API-Key': API_KEY,
            })
            self.timeout = (10, 60)  # Увеличиваем таймаут до 60 секунд
    
    # === КАТЕГОРИИ ===
    def get_categories(self):
        """Получение дерева товарных категорий"""
        if not self.session:
            return {'error': 'API key not configured', 'categories': []}
        
        try:
            response = self.session.get(
                f'{BASE_URL}/catalog/categories',
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {'error': str(e), 'categories': []}
    
    # === ТОВАРЫ ПО КАТЕГОРИЯМ ===
    def get_products_by_category(self, category_code, shipment_city, params=None):
        """Получение товаров по категории"""
        if not self.session:
            return {'error': 'API key not configured', 'products': []}
        
        try:
            url = f'{BASE_URL}/catalog/categories/{category_code}/products'
            query_params = {'shipmentcity': shipment_city}
            
            if params:
                query_params.update(params)
            
            response = self.session.get(
                url,
                params=query_params,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {'error': str(e), 'products': []}
    
    # === ТОВАРЫ ПО СПИСКУ ID ===
    def get_products_by_ids(self, item_ids, shipment_city, params=None):
        """Получение товаров по списку ID"""
        if not self.session:
            return {'error': 'API key not configured', 'products': []}
        
        try:
            url = f'{BASE_URL}/catalog/products/{item_ids}'
            query_params = {'shipmentcity': shipment_city}
            
            if params:
                query_params.update(params)
            
            response = self.session.get(
                url,
                params=query_params,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {'error': str(e), 'products': []}
    
    # === ГОРОДА ОТГРУЗКИ ===
    def get_shipment_cities(self):
        """Получение списка доступных городов отгрузки"""
        if not self.session:
            return {'error': 'API key not configured', 'cities': []}
        
        try:
            response = self.session.get(
                f'{BASE_URL}/logistic/shipment/cities',
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {'error': str(e), 'cities': []}
    
    # === ЛОКАЦИИ ТОВАРА ===
    def get_stock_locations(self, shipment_city):
        """Получение доступных местоположений товара"""
        if not self.session:
            return {'error': 'API key not configured', 'locations': []}
        
        try:
            response = self.session.get(
                f'{BASE_URL}/logistic/stocks/locations',
                params={'shipmentcity': shipment_city},
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {'error': str(e), 'locations': []}

# Инициализация клиента
client = OCSClient()

# ========== ROUTES ==========

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS B2B API',
        'status': 'running',
        'endpoints': {
            'categories': '/categories',
            'products_by_category': '/products/category/<category>/<city>',
            'products_by_ids': '/products/ids/<item_ids>/<city>',
            'cities': '/cities',
            'locations': '/locations/<city>',
            'health': '/health'
        }
    })

@app.route('/categories')
def get_categories():
    """Получение всех категорий"""
    return jsonify(client.get_categories())

@app.route('/products/category/<category>/<city>')
def get_products_by_category(category, city):
    """Получение товаров по категории"""
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': request.args.get('includesale', 'false'),
        'includeuncondition': request.args.get('includeuncondition', 'false'),
    }
    return jsonify(client.get_products_by_category(category, city, params))

@app.route('/products/ids/<item_ids>/<city>')
def get_products_by_ids(item_ids, city):
    """Получение товаров по списку ID"""
    params = {
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': request.args.get('includesale', 'false'),
        'includeuncondition': request.args.get('includeuncondition', 'false'),
    }
    return jsonify(client.get_products_by_ids(item_ids, city, params))

@app.route('/cities')
def get_cities():
    """Получение доступных городов отгрузки"""
    return jsonify(client.get_shipment_cities())

@app.route('/locations/<city>')
def get_locations(city):
    """Получение доступных местоположений товара"""
    return jsonify(client.get_stock_locations(city))

@app.route('/health')
def health():
    """Проверка здоровья API"""
    return jsonify({
        'status': 'ok',
        'ocs_api_configured': bool(API_KEY)
    })

@app.route('/test')
def test():
    """Тестовый эндпоинт"""
    return jsonify({
        'message': 'API is working',
        'timestamp': '2026-01-15T08:00:00Z',
        'test_endpoints': [
            '/cities',
            '/health',
            '/categories'
        ]
    })

# ========== ERROR HANDLERS ==========

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ========== MAIN ==========

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port)