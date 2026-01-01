import os
import requests
import logging
from datetime import datetime
from flask import Flask, jsonify, request, make_response
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
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    response = make_response('', 200)
    response.headers.add('Content-Type', 'application/json')
    return response

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
    
    def _make_request(self, endpoint: str, params=None, method='GET', data=None):
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"OCS API: {url}")
            
            # Увеличиваем таймаут для медленных запросов
            timeout_config = (10, 20)  # (connect timeout, read timeout)
            
            if method == 'GET':
                response = self.session.get(url, params=params, timeout=timeout_config, verify=True)
            elif method == 'POST':
                response = self.session.post(url, params=params, json=data, timeout=timeout_config, verify=True)
            elif method == 'PUT':
                response = self.session.put(url, params=params, json=data, timeout=timeout_config, verify=True)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params, timeout=timeout_config, verify=True)
            else:
                logger.error(f"Unsupported method: {method}")
                return None
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"OCS API Error {response.status_code}: {response.text}")
                return {"error": f"OCS API returned {response.status_code}"}
                
        except requests.exceptions.Timeout:
            logger.error(f"OCS API Timeout: {url}")
            return {"error": "Timeout connecting to OCS API"}
        except requests.exceptions.ConnectionError:
            logger.error(f"OCS API Connection Error: {url}")
            return {"error": "Connection error to OCS API"}
        except Exception as e:
            logger.error(f"OCS API Exception: {e}")
            return {"error": str(e)}

    # Catalog endpoints
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
    
    def get_products_by_ids(self, item_ids: str, shipment_city: str, **params):
        endpoint = f"catalog/products/{item_ids}"
        params['shipmentcity'] = shipment_city
        return self._make_request(endpoint, params=params)
    
    def get_products_batch(self, shipment_city: str, item_ids: list, **params):
        endpoint = "catalog/products/batch"
        params['shipmentcity'] = shipment_city
        return self._make_request(endpoint, params=params, method='POST', data=item_ids)
    
    def get_certificates(self, item_ids: str, actuality='actual'):
        endpoint = f"catalog/products/{item_ids}/certificates"
        params = {'actuality': actuality}
        return self._make_request(endpoint, params=params)
    
    def get_certificates_batch(self, item_ids: list, actuality='actual'):
        endpoint = "catalog/products/batch/certificates"
        params = {'actuality': actuality}
        return self._make_request(endpoint, params=params, method='POST', data=item_ids)
    
    def get_stock_locations(self, shipment_city: str):
        endpoint = "logistic/stocks/locations"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    # Content endpoints
    def get_content(self, item_ids: str):
        endpoint = f"content/{item_ids}"
        return self._make_request(endpoint)
    
    def get_content_batch(self, item_ids: list):
        endpoint = "content/batch"
        return self._make_request(endpoint, method='POST', data=item_ids)
    
    def get_content_changes(self, from_date: str):
        endpoint = "content/changes"
        params = {'from': from_date}
        return self._make_request(endpoint, params=params)
    
    # Orders endpoints
    def get_orders(self, from_date=None, to_date=None, only_active=None):
        endpoint = "orders"
        params = {}
        if from_date:
            params['From'] = from_date
        if to_date:
            params['To'] = to_date
        if only_active is not None:
            params['OnlyActive'] = str(only_active).lower()
        return self._make_request(endpoint, params=params)
    
    def get_order(self, order_id: str):
        endpoint = f"orders/{order_id}"
        return self._make_request(endpoint)
    
    def create_order(self, order_data: dict, synchronous=False):
        endpoint = "orders" if not synchronous else "orders/online/"
        return self._make_request(endpoint, method='POST', data=order_data)
    
    def update_order(self, order_id: str, order_data: dict, synchronous=False):
        endpoint = f"orders/{order_id}" if not synchronous else f"orders/online/{order_id}"
        return self._make_request(endpoint, method='PUT', data=order_data)
    
    def delete_order(self, order_id: str, synchronous=False):
        endpoint = f"orders/{order_id}" if not synchronous else f"orders/online/{order_id}"
        return self._make_request(endpoint, method='DELETE')
    
    def sync_order(self, order_id: str, sync_data: dict, synchronous=False):
        endpoint = f"orders/{order_id}/sync" if not synchronous else f"orders/online/{order_id}/sync"
        return self._make_request(endpoint, method='PUT', data=sync_data)
    
    def transfer_lines_to_manager(self, transfer_data: dict, synchronous=False):
        endpoint = "orders/lines/transfer-to-manager" if not synchronous else "orders/online/lines/transfer-to-manager"
        return self._make_request(endpoint, method='POST', data=transfer_data)
    
    def get_operation_status(self, operation_id: str):
        endpoint = f"orders/operations/{operation_id}"
        return self._make_request(endpoint)
    
    # Account endpoints
    def get_payers(self):
        return self._make_request("account/payers")
    
    def get_contact_persons(self):
        return self._make_request("account/contactpersons")
    
    def get_currencies_exchange(self):
        return self._make_request("account/currencies/exchanges")
    
    def get_finances(self):
        return self._make_request("account/finances")
    
    def get_consignees(self):
        return self._make_request("account/consignees")
    
    # Logistic endpoints
    def get_reserve_places(self):
        return self._make_request("logistic/stocks/reserveplaces")
    
    def get_pickup_points(self, shipment_city: str):
        endpoint = "logistic/shipment/pickup-points"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    def get_delivery_addresses(self, shipment_city: str):
        endpoint = "logistic/shipment/delivery-addresses"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    def get_transport_companies(self, shipment_city: str):
        endpoint = "logistic/shipment/terminal-tc/transport-companies"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    def get_terminal_addresses(self, shipment_city: str):
        endpoint = "logistic/shipment/terminal-tc/addresses"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    # Shipments endpoints
    def create_shipment_stock(self, shipment_data: dict):
        endpoint = "shipments/stock"
        return self._make_request(endpoint, method='POST', data=shipment_data)
    
    def create_shipment_pickup_point(self, shipment_data: dict):
        endpoint = "shipments/pickup-point"
        return self._make_request(endpoint, method='POST', data=shipment_data)
    
    def create_shipment_direct(self, shipment_data: dict):
        endpoint = "shipments/direct"
        return self._make_request(endpoint, method='POST', data=shipment_data)
    
    def create_shipment_terminal_tc(self, shipment_data: dict):
        endpoint = "shipments/terminal-tc"
        return self._make_request(endpoint, method='POST', data=shipment_data)
    
    def get_shipment(self, shipment_id: str):
        endpoint = f"shipments/{shipment_id}"
        return self._make_request(endpoint)
    
    def get_shipment_serial_numbers(self, shipment_id: str):
        endpoint = f"shipments/{shipment_id}/serial-numbers"
        return self._make_request(endpoint)
    
    def get_stock_dates(self, lines_data: dict):
        endpoint = "shipments/stock/dates"
        return self._make_request(endpoint, method='POST', data=lines_data)
    
    def get_pickup_point_dates(self, dates_data: dict):
        endpoint = "shipments/pickup-point/dates"
        return self._make_request(endpoint, method='POST', data=dates_data)
    
    def get_direct_dates(self, dates_data: dict):
        endpoint = "shipments/direct/dates"
        return self._make_request(endpoint, method='POST', data=dates_data)
    
    def get_direct_cost(self, cost_data: dict):
        endpoint = "shipments/direct/cost"
        return self._make_request(endpoint, method='POST', data=cost_data)
    
    def get_terminal_tc_dates(self, dates_data: dict):
        endpoint = "shipments/terminal-tc/dates"
        return self._make_request(endpoint, method='POST', data=dates_data)
    
    def get_terminal_tc_cost(self, cost_data: dict):
        endpoint = "shipments/terminal-tc/cost"
        return self._make_request(endpoint, method='POST', data=cost_data)
    
    # Invoices endpoints
    def get_invoices(self, from_date=None, to_date=None):
        endpoint = "invoices"
        params = {}
        if from_date:
            params['From'] = from_date
        if to_date:
            params['To'] = to_date
        return self._make_request(endpoint, params=params)
    
    # Reports endpoints
    def get_orders_report(self):
        endpoint = "reports/orders"
        return self._make_request(endpoint)

# Инициализация API
api_key = os.getenv('OCS_API_KEY')
if not api_key:
    logger.warning("OCS_API_KEY not found in environment variables")
    ocs_api = None
else:
    logger.info(f"API key loaded, length: {len(api_key)}")
    ocs_api = OCSAPI(api_key=api_key)

@app.route('/')
def home():
    response = jsonify({
        "status": "success", 
        "message": "OCS B2B API Proxy Service v2",
        "version": "2.0.0",
        "api_key_configured": bool(api_key),
        "cors_enabled": True,
        "base_path": "/api/v2/",
        "timestamp": datetime.now().isoformat(),
        "endpoints": [
            "/api/v2/health",
            "/api/v2/test",
            "/api/v2/catalog/categories",
            "/api/v2/logistic/shipment/cities",
            "/api/v2/catalog/categories/{category}/products",
            "/api/v2/orders",
            "/api/v2/account/payers"
        ]
    })
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/health')
def health_check():
    response = jsonify({
        "status": "healthy",
        "service": "OCS API Proxy",
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/test')
def test_api():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY в Render.com"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        cities = ocs_api.get_shipment_cities()
        
        if cities and "error" in cities:
            response = jsonify({
                "success": False,
                "error": cities.get("error"),
                "message": "Ошибка при подключении к OCS API"
            })
        else:
            response = jsonify({
                "success": True,
                "message": "API работает",
                "api_key_configured": True,
                "ocs_api_connection": "success" if cities else "failed",
                "available_cities": cities or []
            })
            
    except Exception as e:
        logger.error(f"Error in test_api: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера"
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/debug')
def debug_info():
    info = {
        "service": "OCS API Proxy v2",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "api": {
            "key_configured": bool(api_key),
            "key_length": len(api_key) if api_key else 0,
        },
        "environment": {
            "on_render": bool(os.getenv('RENDER', False)),
            "port": os.getenv('PORT', '10000')
        }
    }
    
    response = jsonify(info)
    response.headers.add('Content-Type', 'application/json')
    return response

# Catalog endpoints
@app.route('/api/v2/catalog/categories')
def get_categories():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        categories = ocs_api.get_categories()
        
        if categories and "error" in categories:
            response = jsonify({
                "success": False,
                "error": categories.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True,
                "data": categories or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_categories: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/logistic/shipment/cities')
def get_cities():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        cities = ocs_api.get_shipment_cities()
        
        if cities and "error" in cities:
            response = jsonify({
                "success": False,
                "error": cities.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True,
                "data": cities or [],
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_cities: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/categories/<path:category>/products')
def get_products_by_category(category):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    if category in ['undefined', 'null', '']:
        category = 'all'
    
    try:
        products = ocs_api.get_products_by_category(
            categories=category,
            shipment_city=shipment_city,
            **request.args.to_dict()
        )
        
        if products and "error" in products:
            response = jsonify({
                "success": False,
                "error": products.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if products else False,
                "data": products or {"result": []},
                "total_count": len(products.get('result', [])) if products else 0,
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_products_by_category: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/categories/all/products')
def search_products():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    if not search_term:
        response = jsonify({
            "success": False,
            "error": "Не указан поисковый запрос",
            "message": "Используйте параметр q для поиска"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 400
    
    try:
        products = ocs_api.search_products(
            search_term=search_term,
            shipment_city=shipment_city,
            **request.args.to_dict()
        )
        
        if products and "error" in products:
            response = jsonify({
                "success": False,
                "error": products.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if products else False,
                "data": products or {"result": []},
                "search_term": search_term,
                "total_count": len(products.get('result', [])) if products else 0,
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in search_products: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/products/<item_ids>')
def get_products_by_ids(item_ids):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    try:
        products = ocs_api.get_products_by_ids(
            item_ids=item_ids,
            shipment_city=shipment_city,
            **request.args.to_dict()
        )
        
        if products and "error" in products:
            response = jsonify({
                "success": False,
                "error": products.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if products else False,
                "data": products or {"result": []},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_products_by_ids: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/products/batch', methods=['POST'])
def get_products_batch():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается массив itemIds в формате JSON"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        shipment_city = request.args.get('shipment_city', 'Красноярск')
        
        products = ocs_api.get_products_batch(
            shipment_city=shipment_city,
            item_ids=data,
            **request.args.to_dict()
        )
        
        if products and "error" in products:
            response = jsonify({
                "success": False,
                "error": products.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if products else False,
                "data": products or {"result": []},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_products_batch: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/products/<item_ids>/certificates')
def get_certificates(item_ids):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    actuality = request.args.get('actuality', 'actual')
    
    try:
        certificates = ocs_api.get_certificates(
            item_ids=item_ids,
            actuality=actuality
        )
        
        if certificates and "error" in certificates:
            response = jsonify({
                "success": False,
                "error": certificates.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if certificates else False,
                "data": certificates or {"result": []},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_certificates: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/catalog/products/batch/certificates', methods=['POST'])
def get_certificates_batch():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается массив itemIds в формате JSON"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        actuality = request.args.get('actuality', 'actual')
        
        certificates = ocs_api.get_certificates_batch(
            item_ids=data,
            actuality=actuality
        )
        
        if certificates and "error" in certificates:
            response = jsonify({
                "success": False,
                "error": certificates.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if certificates else False,
                "data": certificates or {"result": []},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_certificates_batch: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/logistic/stocks/locations')
def get_stock_locations():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    try:
        locations = ocs_api.get_stock_locations(shipment_city=shipment_city)
        
        if locations and "error" in locations:
            response = jsonify({
                "success": False,
                "error": locations.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if locations else False,
                "data": locations or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_stock_locations: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

# Content endpoints
@app.route('/api/v2/content/<item_ids>')
def get_content(item_ids):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        content = ocs_api.get_content(item_ids=item_ids)
        
        if content and "error" in content:
            response = jsonify({
                "success": False,
                "error": content.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if content else False,
                "data": content or {"result": []},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_content: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/content/batch', methods=['POST'])
def get_content_batch():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data or not isinstance(data, list):
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается массив itemIds в формате JSON"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        content = ocs_api.get_content_batch(item_ids=data)
        
        if content and "error" in content:
            response = jsonify({
                "success": False,
                "error": content.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if content else False,
                "data": content or {"result": []},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_content_batch: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/content/changes')
def get_content_changes():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    from_date = request.args.get('from')
    if not from_date:
        response = jsonify({
            "success": False,
            "error": "Не указана дата начала периода",
            "message": "Используйте параметр from для указания даты"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 400
    
    try:
        changes = ocs_api.get_content_changes(from_date=from_date)
        
        if changes and "error" in changes:
            response = jsonify({
                "success": False,
                "error": changes.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if changes else False,
                "data": changes or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_content_changes: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

# Orders endpoints
@app.route('/api/v2/orders')
def get_orders():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    from_date = request.args.get('From')
    to_date = request.args.get('To')
    only_active = request.args.get('OnlyActive')
    
    try:
        orders = ocs_api.get_orders(
            from_date=from_date,
            to_date=to_date,
            only_active=only_active
        )
        
        if orders and "error" in orders:
            response = jsonify({
                "success": False,
                "error": orders.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if orders else False,
                "data": orders or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_orders: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/orders/<order_id>')
def get_order(order_id):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        order = ocs_api.get_order(order_id=order_id)
        
        if order and "error" in order:
            response = jsonify({
                "success": False,
                "error": order.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if order else False,
                "data": order or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_order: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/orders', methods=['POST'])
def create_order():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными заказа"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        synchronous = request.args.get('synchronous', 'false').lower() == 'true'
        
        order = ocs_api.create_order(order_data=data, synchronous=synchronous)
        
        if order and "error" in order:
            response = jsonify({
                "success": False,
                "error": order.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if order else False,
                "data": order or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in create_order: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/orders/<order_id>', methods=['PUT'])
def update_order(order_id):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными для обновления"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        synchronous = request.args.get('synchronous', 'false').lower() == 'true'
        
        order = ocs_api.update_order(order_id=order_id, order_data=data, synchronous=synchronous)
        
        if order and "error" in order:
            response = jsonify({
                "success": False,
                "error": order.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if order else False,
                "data": order or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in update_order: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/orders/<order_id>', methods=['DELETE'])
def delete_order(order_id):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        synchronous = request.args.get('synchronous', 'false').lower() == 'true'
        
        order = ocs_api.delete_order(order_id=order_id, synchronous=synchronous)
        
        if order and "error" in order:
            response = jsonify({
                "success": False,
                "error": order.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if order else False,
                "data": order or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in delete_order: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/orders/<order_id>/sync', methods=['PUT'])
def sync_order(order_id):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными для синхронизации"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        synchronous = request.args.get('synchronous', 'false').lower() == 'true'
        
        order = ocs_api.sync_order(order_id=order_id, sync_data=data, synchronous=synchronous)
        
        if order and "error" in order:
            response = jsonify({
                "success": False,
                "error": order.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if order else False,
                "data": order or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in sync_order: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/orders/lines/transfer-to-manager', methods=['POST'])
def transfer_lines_to_manager():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными для передачи"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        synchronous = request.args.get('synchronous', 'false').lower() == 'true'
        
        result = ocs_api.transfer_lines_to_manager(transfer_data=data, synchronous=synchronous)
        
        if result and "error" in result:
            response = jsonify({
                "success": False,
                "error": result.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if result else False,
                "data": result or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in transfer_lines_to_manager: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/orders/operations/<operation_id>')
def get_operation_status(operation_id):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        status = ocs_api.get_operation_status(operation_id=operation_id)
        
        if status and "error" in status:
            response = jsonify({
                "success": False,
                "error": status.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if status else False,
                "data": status or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_operation_status: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

# Account endpoints
@app.route('/api/v2/account/payers')
def get_payers():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        payers = ocs_api.get_payers()
        
        if payers and "error" in payers:
            response = jsonify({
                "success": False,
                "error": payers.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if payers else False,
                "data": payers or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_payers: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/account/contactpersons')
def get_contact_persons():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        contact_persons = ocs_api.get_contact_persons()
        
        if contact_persons and "error" in contact_persons:
            response = jsonify({
                "success": False,
                "error": contact_persons.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if contact_persons else False,
                "data": contact_persons or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_contact_persons: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/account/currencies/exchanges')
def get_currencies_exchange():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        exchanges = ocs_api.get_currencies_exchange()
        
        if exchanges and "error" in exchanges:
            response = jsonify({
                "success": False,
                "error": exchanges.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if exchanges else False,
                "data": exchanges or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_currencies_exchange: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/account/finances')
def get_finances():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        finances = ocs_api.get_finances()
        
        if finances and "error" in finances:
            response = jsonify({
                "success": False,
                "error": finances.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if finances else False,
                "data": finances or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_finances: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/account/consignees')
def get_consignees():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        consignees = ocs_api.get_consignees()
        
        if consignees and "error" in consignees:
            response = jsonify({
                "success": False,
                "error": consignees.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if consignees else False,
                "data": consignees or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_consignees: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

# Logistic endpoints
@app.route('/api/v2/logistic/stocks/reserveplaces')
def get_reserve_places():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        reserve_places = ocs_api.get_reserve_places()
        
        if reserve_places and "error" in reserve_places:
            response = jsonify({
                "success": False,
                "error": reserve_places.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if reserve_places else False,
                "data": reserve_places or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_reserve_places: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/logistic/shipment/pickup-points')
def get_pickup_points():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    try:
        pickup_points = ocs_api.get_pickup_points(shipment_city=shipment_city)
        
        if pickup_points and "error" in pickup_points:
            response = jsonify({
                "success": False,
                "error": pickup_points.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if pickup_points else False,
                "data": pickup_points or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_pickup_points: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/logistic/shipment/delivery-addresses')
def get_delivery_addresses():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    try:
        addresses = ocs_api.get_delivery_addresses(shipment_city=shipment_city)
        
        if addresses and "error" in addresses:
            response = jsonify({
                "success": False,
                "error": addresses.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if addresses else False,
                "data": addresses or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_delivery_addresses: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/logistic/shipment/terminal-tc/transport-companies')
def get_transport_companies():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    try:
        companies = ocs_api.get_transport_companies(shipment_city=shipment_city)
        
        if companies and "error" in companies:
            response = jsonify({
                "success": False,
                "error": companies.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if companies else False,
                "data": companies or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_transport_companies: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/logistic/shipment/terminal-tc/addresses')
def get_terminal_addresses():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    try:
        addresses = ocs_api.get_terminal_addresses(shipment_city=shipment_city)
        
        if addresses and "error" in addresses:
            response = jsonify({
                "success": False,
                "error": addresses.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if addresses else False,
                "data": addresses or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_terminal_addresses: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

# Shipments endpoints
@app.route('/api/v2/shipments/stock', methods=['POST'])
def create_shipment_stock():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными отгрузки"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        shipment = ocs_api.create_shipment_stock(shipment_data=data)
        
        if shipment and "error" in shipment:
            response = jsonify({
                "success": False,
                "error": shipment.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if shipment else False,
                "data": shipment or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in create_shipment_stock: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/pickup-point', methods=['POST'])
def create_shipment_pickup_point():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными отгрузки"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        shipment = ocs_api.create_shipment_pickup_point(shipment_data=data)
        
        if shipment and "error" in shipment:
            response = jsonify({
                "success": False,
                "error": shipment.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if shipment else False,
                "data": shipment or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in create_shipment_pickup_point: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/direct', methods=['POST'])
def create_shipment_direct():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными отгрузки"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        shipment = ocs_api.create_shipment_direct(shipment_data=data)
        
        if shipment and "error" in shipment:
            response = jsonify({
                "success": False,
                "error": shipment.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if shipment else False,
                "data": shipment or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in create_shipment_direct: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/terminal-tc', methods=['POST'])
def create_shipment_terminal_tc():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными отгрузки"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        shipment = ocs_api.create_shipment_terminal_tc(shipment_data=data)
        
        if shipment and "error" in shipment:
            response = jsonify({
                "success": False,
                "error": shipment.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if shipment else False,
                "data": shipment or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in create_shipment_terminal_tc: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/<shipment_id>')
def get_shipment(shipment_id):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        shipment = ocs_api.get_shipment(shipment_id=shipment_id)
        
        if shipment and "error" in shipment:
            response = jsonify({
                "success": False,
                "error": shipment.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if shipment else False,
                "data": shipment or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_shipment: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/<shipment_id>/serial-numbers')
def get_shipment_serial_numbers(shipment_id):
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        serial_numbers = ocs_api.get_shipment_serial_numbers(shipment_id=shipment_id)
        
        if serial_numbers and "error" in serial_numbers:
            response = jsonify({
                "success": False,
                "error": serial_numbers.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if serial_numbers else False,
                "data": serial_numbers or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_shipment_serial_numbers: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/stock/dates', methods=['POST'])
def get_stock_dates():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными строк заказа"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        dates = ocs_api.get_stock_dates(lines_data=data)
        
        if dates and "error" in dates:
            response = jsonify({
                "success": False,
                "error": dates.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if dates else False,
                "data": dates or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_stock_dates: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/pickup-point/dates', methods=['POST'])
def get_pickup_point_dates():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными для расчета дат"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        dates = ocs_api.get_pickup_point_dates(dates_data=data)
        
        if dates and "error" in dates:
            response = jsonify({
                "success": False,
                "error": dates.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if dates else False,
                "data": dates or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_pickup_point_dates: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/direct/dates', methods=['POST'])
def get_direct_dates():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными для расчета дат"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        dates = ocs_api.get_direct_dates(dates_data=data)
        
        if dates and "error" in dates:
            response = jsonify({
                "success": False,
                "error": dates.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if dates else False,
                "data": dates or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_direct_dates: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/direct/cost', methods=['POST'])
def get_direct_cost():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными для расчета стоимости"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        cost = ocs_api.get_direct_cost(cost_data=data)
        
        if cost and "error" in cost:
            response = jsonify({
                "success": False,
                "error": cost.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if cost else False,
                "data": cost or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_direct_cost: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/terminal-tc/dates', methods=['POST'])
def get_terminal_tc_dates():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными для расчета дат"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        dates = ocs_api.get_terminal_tc_dates(dates_data=data)
        
        if dates and "error" in dates:
            response = jsonify({
                "success": False,
                "error": dates.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if dates else False,
                "data": dates or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_terminal_tc_dates: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

@app.route('/api/v2/shipments/terminal-tc/cost', methods=['POST'])
def get_terminal_tc_cost():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({
                "success": False,
                "error": "Неверный формат данных",
                "message": "Ожидается JSON объект с данными для расчета стоимости"
            })
            response.headers.add('Content-Type', 'application/json')
            return response, 400
        
        cost = ocs_api.get_terminal_tc_cost(cost_data=data)
        
        if cost and "error" in cost:
            response = jsonify({
                "success": False,
                "error": cost.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if cost else False,
                "data": cost or {},
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_terminal_tc_cost: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

# Invoices endpoints
@app.route('/api/v2/invoices')
def get_invoices():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    from_date = request.args.get('From')
    to_date = request.args.get('To')
    
    try:
        invoices = ocs_api.get_invoices(from_date=from_date, to_date=to_date)
        
        if invoices and "error" in invoices:
            response = jsonify({
                "success": False,
                "error": invoices.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if invoices else False,
                "data": invoices or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_invoices: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

# Reports endpoints
@app.route('/api/v2/reports/orders')
def get_orders_report():
    if not ocs_api:
        response = jsonify({
            "success": False, 
            "error": "API ключ не настроен",
            "message": "Установите переменную окружения OCS_API_KEY"
        })
        response.headers.add('Content-Type', 'application/json')
        return response, 500
    
    try:
        report = ocs_api.get_orders_report()
        
        if report and "error" in report:
            response = jsonify({
                "success": False,
                "error": report.get("error"),
                "message": "Ошибка при подключении к OCS API",
                "timestamp": datetime.now().isoformat()
            })
        else:
            response = jsonify({
                "success": True if report else False,
                "data": report or [],
                "source": "ocs_api",
                "timestamp": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error in get_orders_report: {e}")
        response = jsonify({
            "success": False,
            "error": str(e),
            "message": "Внутренняя ошибка сервера",
            "timestamp": datetime.now().isoformat()
        })
    
    response.headers.add('Content-Type', 'application/json')
    return response

# Backward compatibility - старые эндпоинты для обратной совместимости
@app.route('/api/categories')
def old_get_categories():
    response = jsonify({
        "success": False,
        "error": "Эндпоинт устарел",
        "message": "Используйте /api/v2/catalog/categories",
        "new_endpoint": "/api/v2/catalog/categories",
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response, 301

@app.route('/api/health')
def old_health_check():
    response = jsonify({
        "success": False,
        "error": "Эндпоинт устарел",
        "message": "Используйте /api/v2/health",
        "new_endpoint": "/api/v2/health",
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response, 301

@app.route('/api/test')
def old_test_api():
    response = jsonify({
        "success": False,
        "error": "Эндпоинт устарел",
        "message": "Используйте /api/v2/test",
        "new_endpoint": "/api/v2/test",
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response, 301

@app.route('/api/cities')
def old_get_cities():
    response = jsonify({
        "success": False,
        "error": "Эндпоинт устарел",
        "message": "Используйте /api/v2/logistic/shipment/cities",
        "new_endpoint": "/api/v2/logistic/shipment/cities",
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response, 301

@app.route('/api/products/category')
def old_get_products_by_category():
    response = jsonify({
        "success": False,
        "error": "Эндпоинт устарел",
        "message": "Используйте /api/v2/catalog/categories/{category}/products",
        "new_endpoint": "/api/v2/catalog/categories/{category}/products",
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response, 301

@app.route('/api/products/search')
def old_search_products():
    response = jsonify({
        "success": False,
        "error": "Эндпоинт устарел",
        "message": "Используйте /api/v2/catalog/categories/all/products",
        "new_endpoint": "/api/v2/catalog/categories/all/products",
        "timestamp": datetime.now().isoformat()
    })
    response.headers.add('Content-Type', 'application/json')
    return response, 301

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)