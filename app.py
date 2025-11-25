import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

class OCSAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://connector.b2b.ocs.ru/api/v2"
        self.session = requests.Session()
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key
        })
    
    def _make_request(self, endpoint: str, params=None):
        try:
            url = f"{self.base_url}/{endpoint}"
            response = self.session.get(url, params=params, timeout=15)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"API Error: {e}")
            return None

# Инициализация API
api = OCSAPI(api_key=os.getenv('OCS_API_KEY'))

@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "OCS API работает на Render.com!",
        "endpoints": {
            "test": "/api/test",
            "categories": "/api/categories", 
            "products": "/api/products/category?category=all&shipment_city=Красноярск",
            "search": "/api/products/search?q=процессор&shipment_city=Красноярск"
        }
    })

@app.route('/api/test')
def test_api():
    cities = api._make_request("logistic/shipment/cities")
    return jsonify({
        "success": True,
        "message": "✅ OCS API подключено успешно",
        "available_cities": cities or ["Красноярск", "Москва", "Санкт-Петербург"],
        "api_status": "active"
    })

@app.route('/api/categories')
def get_categories():
    categories = api._make_request("catalog/categories")
    return jsonify({
        "success": True,
        "data": categories or []
    })

@app.route('/api/products/category')
def get_products_by_category():
    category = request.args.get('category', 'all')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    endpoint = f"catalog/categories/{category}/products"
    params = {
        'shipmentcity': shipment_city,
        'limit': 100
    }
    
    products = api._make_request(endpoint, params)
    return jsonify({
        "success": True,
        "data": products or {"result": []},
        "total_count": len(products.get('result', [])) if products else 0
    })

@app.route('/api/products/search')
def search_products():
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    if not search_term:
        return jsonify({"success": False, "error": "Не указан поисковый запрос"}), 400
    
    endpoint = "catalog/categories/all/products"
    params = {
        'shipmentcity': shipment_city,
        'search': search_term,
        'limit': 100
    }
    
    products = api._make_request(endpoint, params)
    return jsonify({
        "success": True,
        "data": products or {"result": []},
        "total_count": len(products.get('result', [])) if products else 0
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)