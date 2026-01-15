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
        self.session = requests.Session() if API_KEY else None
        if self.session:
            self.session.headers.update({
                'accept': 'application/json',
                'X-API-Key': API_KEY,
            })
            self.timeout = (10, 30)  # 10 сек на соединение, 30 на чтение
    
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
        """
        Получение товаров по категории
        
        Args:
            category_code: Код категории или 'all' для всех
            shipment_city: Город отгрузки
            params: Дополнительные параметры
        """
        if not self.session:
            return {'error': 'API key not configured', 'products': []}
        
        try:
            url = f'{BASE_URL}/catalog/categories/{category_code}/products'
            
            # Базовые параметры
            query_params = {'shipmentcity': shipment_city}
            
            # Добавляем дополнительные параметры
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
        """
        Получение товаров по списку ID
        
        Args:
            item_ids: Список ID товаров через запятую или 'all'
            shipment_city: Город отгрузки
            params: Дополнительные параметры
        """
        if not self.session:
            return {'error': 'API key not configured', 'products': []}
        
        try:
            url = f'{BASE_URL}/catalog/products/{item_ids}'
            
            # Базовые параметры
            query_params = {'shipmentcity': shipment_city}
            
            # Добавляем дополнительные параметры
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
    
    # === BATCH ВЕРСИЯ ТОВАРОВ ПО ID ===
    def get_products_batch(self, item_ids_list, shipment_city, params=None):
        """
        Batch версия получения товаров (POST запрос)
        
        Args:
            item_ids_list: Список ID товаров ['1000459749', '1000459646', ...]
            shipment_city: Город отгрузки
            params: Дополнительные параметры
        """
        if not self.session:
            return {'error': 'API key not configured', 'products': []}
        
        try:
            url = f'{BASE_URL}/catalog/products/batch'
            
            # Базовые параметры
            query_params = {'shipmentcity': shipment_city}
            
            # Добавляем дополнительные параметры
            if params:
                query_params.update(params)
            
            response = self.session.post(
                url,
                params=query_params,
                json=item_ids_list,  # Тело запроса с массивом ID
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {'error': str(e), 'products': []}
    
    # === ПОЛУЧЕНИЕ ГОРОДОВ ОТГРУЗКИ ===
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
    
    # === ПОЛУЧЕНИЕ ЛОКАЦИЙ ТОВАРА ===
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
    
    # === ПОЛУЧЕНИЕ СЕРТИФИКАТОВ ===
    def get_certificates(self, item_ids, actuality='actual'):
        """
        Получение сертификатов для товаров
        
        Args:
            item_ids: Список ID товаров через запятую
            actuality: 'actual' - только действующие, 'expired' - истекшие, 'all' - все
        """
        if not self.session:
            return {'error': 'API key not configured', 'certificates': []}
        
        try:
            response = self.session.get(
                f'{BASE_URL}/catalog/products/{item_ids}/certificates',
                params={'actuality': actuality},
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {'error': str(e), 'certificates': []}

# Инициализация клиента
client = OCSClient()

# ========== ROUTES ==========

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS B2B API Wrapper',
        'version': '1.0',
        'endpoints': {
            'categories': '/categories',
            'products_by_category': '/products/category/<category>/<city>',
            'products_by_ids': '/products/ids/<item_ids>/<city>',
            'products_batch': '/products/batch/<city> (POST)',
            'cities': '/cities',
            'locations': '/locations/<city>',
            'certificates': '/certificates/<item_ids>',
            'health': '/health',
            'test': '/test'
        },
        'documentation': 'См. API-коннектор B2B документацию OCS'
    })

@app.route('/categories')
def get_categories():
    """Получение всех категорий"""
    return jsonify(client.get_categories())

@app.route('/products/category/<category>/<city>')
def get_products_by_category(category, city):
    """
    Получение товаров по категории
    
    Query параметры:
    - onlyavailable: true/false (только доступные)
    - includeregular: true/false (кондиционные)
    - includesale: true/false (распродажа)
    - includeuncondition: true/false (некондиция)
    - includemissing: true/false (отсутствующие)
    """
    params = {
        'onlyavailable': request.args.get('onlyavailable', 'true'),
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': request.args.get('includesale', 'false'),
        'includeuncondition': request.args.get('includeuncondition', 'false'),
        'includemissing': request.args.get('includemissing', 'false'),
        'withdescriptions': request.args.get('withdescriptions', 'true'),
    }
    return jsonify(client.get_products_by_category(category, city, params))

@app.route('/products/ids/<item_ids>/<city>')
def get_products_by_ids(item_ids, city):
    """
    Получение товаров по списку ID
    
    Query параметры (аналогично категориям)
    """
    params = {
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': request.args.get('includesale', 'false'),
        'includeuncondition': request.args.get('includeuncondition', 'false'),
    }
    return jsonify(client.get_products_by_ids(item_ids, city, params))

@app.route('/products/batch/<city>', methods=['POST'])
def get_products_batch(city):
    """
    Batch получение товаров (POST)
    
    Тело запроса: JSON массив ID товаров
    ["1000459749", "1000459646", ...]
    
    Query параметры (аналогично)
    """
    from flask import request
    
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    item_ids = request.get_json()
    if not isinstance(item_ids, list):
        return jsonify({'error': 'Request body must be a list of item IDs'}), 400
    
    params = {
        'includeregular': request.args.get('includeregular', 'true'),
        'includesale': request.args.get('includesale', 'false'),
        'includeuncondition': request.args.get('includeuncondition', 'false'),
    }
    
    return jsonify(client.get_products_batch(item_ids, city, params))

@app.route('/cities')
def get_cities():
    """Получение доступных городов отгрузки"""
    return jsonify(client.get_shipment_cities())

@app.route('/locations/<city>')
def get_locations(city):
    """Получение доступных местоположений товара"""
    return jsonify(client.get_stock_locations(city))

@app.route('/certificates/<item_ids>')
def get_certificates(item_ids):
    """
    Получение сертификатов для товаров
    
    Query параметры:
    - actuality: actual/expired/all (по умолчанию: actual)
    """
    actuality = request.args.get('actuality', 'actual')
    return jsonify(client.get_certificates(item_ids, actuality))

@app.route('/health')
def health():
    """Проверка здоровья API"""
    return jsonify({
        'status': 'ok',
        'ocs_api_configured': bool(API_KEY),
        'api_key_length': len(API_KEY) if API_KEY else 0
    })

@app.route('/test')
def test():
    """Тестовый эндпоинт"""
    return jsonify({
        'message': 'OCS API Wrapper is working',
        'endpoints_available': [
            '/categories',
            '/products/category/all/Москва',
            '/products/ids/1000459749,1000459646/Москва',
            '/cities',
            '/locations/Москва'
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
    
    print("=" * 60)
    print("OCS B2B API Wrapper")
    print("=" * 60)
    print(f"API Key configured: {'YES' if API_KEY else 'NO'}")
    print(f"Server URL: http://0.0.0.0:{port}")
    print("=" * 60)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False  # False для production
    )