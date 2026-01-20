import os
import requests
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)
CORS(app)
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response
@app.route('/api/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    return '', 200
class OCSAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://connector.b2b.ocs.ru/api/v2"
        self.session = requests.Session()
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': 'OCS-Integration/1.0'
        })
    
    def _make_request(self, endpoint: str, params=None):
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"OCS API: {url}")
            
            response = self.session.get(url, params=params, timeout=10, verify=True)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"OCS API Error {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"OCS API Exception: {e}")
            return None
    def get_categories(self):
        return self._make_request("catalog/categories")
    
    def get_shipment_cities(self):
        return self._make_request("logistic/shipment/cities")
    
    def get_products_by_category(self, categories: str, shipment_city: str, **params):
        endpoint = f"catalog/categories/{categories}/products"
        params['shipmentcity'] = shipment_city
        params['limit'] = params.get('limit', 50)
        return self._make_request(endpoint, params=params)
    
    def search_products(self, search_term: str, shipment_city: str, **params):
        endpoint = f"catalog/categories/all/products"
        params['shipmentcity'] = shipment_city
        params['search'] = search_term
        params['limit'] = params.get('limit', 50)
        return self._make_request(endpoint, params=params)
# Инициализация API
api_key = os.getenv('OCS_API_KEY')
ocs_api = OCSAPI(api_key=api_key) if api_key else None
@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "OCS API работает на Render.com!",
        "api_key_configured": bool(api_key),
        "cors_enabled": True
    })
@app.route('/api/health')
def health_check():
    return jsonify({"status": "healthy"})
@app.route('/api/test')
def test_api():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    cities = ocs_api.get_shipment_cities()
    
    return jsonify({
        "success": True,
        "message": "API работает",
        "api_key_configured": True,
        "ocs_api_connection": "success" if cities else "failed",
        "available_cities": cities or []
    })
@app.route('/api/categories')
def get_categories():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    categories = ocs_api.get_categories()
    
    return jsonify({
        "success": True,
        "data": categories or [],
        "source": "ocs_api"
    })
@app.route('/api/cities')
def get_cities():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    cities = ocs_api.get_shipment_cities()
    
    return jsonify({
        "success": True,
        "data": cities or []
    })
@app.route('/api/products/category')
def get_products_by_category():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
        
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')

    # Логируем параметры для отладки
    #logger.info(f"Products request - category: '{category}', city: '{shipment_city}'")

    if category in ['undefined', 'null', '']:
        category = 'all'

    products = ocs_api.get_products_by_category(
        categories=category,
        shipment_city=shipment_city
    )
    
    return jsonify({
        "success": True if products else False,
        "data": products or {"result": []},
        "total_count": len(products.get('result', [])) if products else 0,
        "source": "ocs_api"
    })
@app.route('/api/products/search')
def search_products():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    if not search_term:
        return jsonify({"success": False, "error": "Не указан поисковый запрос"}), 400
    
    products = ocs_api.search_products(
        search_term=search_term,
        shipment_city=shipment_city
    )
    
    return jsonify({
        "success": True if products else False,
        "data": products or {"result": []},
        "search_term": search_term,
        "total_count": len(products.get('result', [])) if products else 0,
        "source": "ocs_api"
    })
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)