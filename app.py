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

@app.route('/api/v2/v2/<path:path>', methods=['OPTIONS'])
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
    
    def _make_request(self, endpoint: str, params=None, method='GET', data=None):
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"OCS API: {url}")
            
            if method == 'GET':
                response = self.session.get(url, params=params, timeout=10, verify=True)
            elif method == 'POST':
                response = self.session.post(url, params=params, json=data, timeout=10, verify=True)
            elif method == 'PUT':
                response = self.session.put(url, params=params, json=data, timeout=10, verify=True)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params, timeout=10, verify=True)
            else:
                logger.error(f"Unsupported method: {method}")
                return None
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"OCS API Error {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"OCS API Exception: {e}")
            return None

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
ocs_api = OCSAPI(api_key=api_key) if api_key else None

@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "OCS B2B API Proxy Service",
        "version": "1.0.0",
        "api_key_configured": bool(api_key),
        "cors_enabled": True
    })

@app.route('/api/v2/health')
def health_check():
    return jsonify({"status": "healthy"})

@app.route('/api/v2/test')
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

# Catalog endpoints
@app.route('/api/v2/catalog/categories')
def get_categories():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    categories = ocs_api.get_categories()
    
    return jsonify({
        "success": True,
        "data": categories or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/logistic/shipment/cities')
def get_cities():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    cities = ocs_api.get_shipment_cities()
    
    return jsonify({
        "success": True,
        "data": cities or []
    })

@app.route('/api/v2/catalog/categories/<path:category>/products')
def get_products_by_category(category):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    if category in ['undefined', 'null', '']:
        category = 'all'
    
    products = ocs_api.get_products_by_category(
        categories=category,
        shipment_city=shipment_city,
        **request.args.to_dict()
    )
    
    return jsonify({
        "success": True if products else False,
        "data": products or {"result": []},
        "total_count": len(products.get('result', [])) if products else 0,
        "source": "ocs_api"
    })

@app.route('/api/v2/catalog/categories/all/products')
def search_products():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    search_term = request.args.get('q', '')
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    if not search_term:
        return jsonify({"success": False, "error": "Не указан поисковый запрос"}), 400
    
    products = ocs_api.search_products(
        search_term=search_term,
        shipment_city=shipment_city,
        **request.args.to_dict()
    )
    
    return jsonify({
        "success": True if products else False,
        "data": products or {"result": []},
        "search_term": search_term,
        "total_count": len(products.get('result', [])) if products else 0,
        "source": "ocs_api"
    })

@app.route('/api/v2/catalog/products/<item_ids>')
def get_products_by_ids(item_ids):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    products = ocs_api.get_products_by_ids(
        item_ids=item_ids,
        shipment_city=shipment_city,
        **request.args.to_dict()
    )
    
    return jsonify({
        "success": True if products else False,
        "data": products or {"result": []},
        "source": "ocs_api"
    })

@app.route('/api/v2/catalog/products/batch', methods=['POST'])
def get_products_batch():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({"success": False, "error": "Неверный формат данных. Ожидается массив itemIds"}), 400
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    products = ocs_api.get_products_batch(
        shipment_city=shipment_city,
        item_ids=data,
        **request.args.to_dict()
    )
    
    return jsonify({
        "success": True if products else False,
        "data": products or {"result": []},
        "source": "ocs_api"
    })

@app.route('/api/v2/catalog/products/<item_ids>/certificates')
def get_certificates(item_ids):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    actuality = request.args.get('actuality', 'actual')
    
    certificates = ocs_api.get_certificates(
        item_ids=item_ids,
        actuality=actuality
    )
    
    return jsonify({
        "success": True if certificates else False,
        "data": certificates or {"result": []},
        "source": "ocs_api"
    })

@app.route('/api/v2/catalog/products/batch/certificates', methods=['POST'])
def get_certificates_batch():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({"success": False, "error": "Неверный формат данных. Ожидается массив itemIds"}), 400
    
    actuality = request.args.get('actuality', 'actual')
    
    certificates = ocs_api.get_certificates_batch(
        item_ids=data,
        actuality=actuality
    )
    
    return jsonify({
        "success": True if certificates else False,
        "data": certificates or {"result": []},
        "source": "ocs_api"
    })

@app.route('/api/v2/logistic/stocks/locations')
def get_stock_locations():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    locations = ocs_api.get_stock_locations(shipment_city=shipment_city)
    
    return jsonify({
        "success": True if locations else False,
        "data": locations or [],
        "source": "ocs_api"
    })

# Content endpoints
@app.route('/api/v2/content/<item_ids>')
def get_content(item_ids):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    content = ocs_api.get_content(item_ids=item_ids)
    
    return jsonify({
        "success": True if content else False,
        "data": content or {"result": []},
        "source": "ocs_api"
    })

@app.route('/api/v2/content/batch', methods=['POST'])
def get_content_batch():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({"success": False, "error": "Неверный формат данных. Ожидается массив itemIds"}), 400
    
    content = ocs_api.get_content_batch(item_ids=data)
    
    return jsonify({
        "success": True if content else False,
        "data": content or {"result": []},
        "source": "ocs_api"
    })

@app.route('/api/v2/content/changes')
def get_content_changes():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    from_date = request.args.get('from')
    if not from_date:
        return jsonify({"success": False, "error": "Не указана дата начала периода (from)"}), 400
    
    changes = ocs_api.get_content_changes(from_date=from_date)
    
    return jsonify({
        "success": True if changes else False,
        "data": changes or [],
        "source": "ocs_api"
    })

# Orders endpoints
@app.route('/api/v2/orders')
def get_orders():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    from_date = request.args.get('From')
    to_date = request.args.get('To')
    only_active = request.args.get('OnlyActive')
    
    orders = ocs_api.get_orders(
        from_date=from_date,
        to_date=to_date,
        only_active=only_active
    )
    
    return jsonify({
        "success": True if orders else False,
        "data": orders or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/orders/<order_id>')
def get_order(order_id):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    order = ocs_api.get_order(order_id=order_id)
    
    return jsonify({
        "success": True if order else False,
        "data": order or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/orders', methods=['POST'])
def create_order():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    synchronous = request.args.get('synchronous', 'false').lower() == 'true'
    
    order = ocs_api.create_order(order_data=data, synchronous=synchronous)
    
    return jsonify({
        "success": True if order else False,
        "data": order or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/orders/<order_id>', methods=['PUT'])
def update_order(order_id):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    synchronous = request.args.get('synchronous', 'false').lower() == 'true'
    
    order = ocs_api.update_order(order_id=order_id, order_data=data, synchronous=synchronous)
    
    return jsonify({
        "success": True if order else False,
        "data": order or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/orders/<order_id>', methods=['DELETE'])
def delete_order(order_id):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    synchronous = request.args.get('synchronous', 'false').lower() == 'true'
    
    order = ocs_api.delete_order(order_id=order_id, synchronous=synchronous)
    
    return jsonify({
        "success": True if order else False,
        "data": order or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/orders/<order_id>/sync', methods=['PUT'])
def sync_order(order_id):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    synchronous = request.args.get('synchronous', 'false').lower() == 'true'
    
    order = ocs_api.sync_order(order_id=order_id, sync_data=data, synchronous=synchronous)
    
    return jsonify({
        "success": True if order else False,
        "data": order or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/orders/lines/transfer-to-manager', methods=['POST'])
def transfer_lines_to_manager():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    synchronous = request.args.get('synchronous', 'false').lower() == 'true'
    
    result = ocs_api.transfer_lines_to_manager(transfer_data=data, synchronous=synchronous)
    
    return jsonify({
        "success": True if result else False,
        "data": result or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/orders/operations/<operation_id>')
def get_operation_status(operation_id):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    status = ocs_api.get_operation_status(operation_id=operation_id)
    
    return jsonify({
        "success": True if status else False,
        "data": status or {},
        "source": "ocs_api"
    })

# Account endpoints
@app.route('/api/v2/account/payers')
def get_payers():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    payers = ocs_api.get_payers()
    
    return jsonify({
        "success": True if payers else False,
        "data": payers or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/account/contactpersons')
def get_contact_persons():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    contact_persons = ocs_api.get_contact_persons()
    
    return jsonify({
        "success": True if contact_persons else False,
        "data": contact_persons or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/account/currencies/exchanges')
def get_currencies_exchange():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    exchanges = ocs_api.get_currencies_exchange()
    
    return jsonify({
        "success": True if exchanges else False,
        "data": exchanges or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/account/finances')
def get_finances():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    finances = ocs_api.get_finances()
    
    return jsonify({
        "success": True if finances else False,
        "data": finances or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/account/consignees')
def get_consignees():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    consignees = ocs_api.get_consignees()
    
    return jsonify({
        "success": True if consignees else False,
        "data": consignees or [],
        "source": "ocs_api"
    })

# Logistic endpoints
@app.route('/api/v2/logistic/stocks/reserveplaces')
def get_reserve_places():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    reserve_places = ocs_api.get_reserve_places()
    
    return jsonify({
        "success": True if reserve_places else False,
        "data": reserve_places or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/logistic/shipment/pickup-points')
def get_pickup_points():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    pickup_points = ocs_api.get_pickup_points(shipment_city=shipment_city)
    
    return jsonify({
        "success": True if pickup_points else False,
        "data": pickup_points or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/logistic/shipment/delivery-addresses')
def get_delivery_addresses():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    addresses = ocs_api.get_delivery_addresses(shipment_city=shipment_city)
    
    return jsonify({
        "success": True if addresses else False,
        "data": addresses or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/logistic/shipment/terminal-tc/transport-companies')
def get_transport_companies():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    companies = ocs_api.get_transport_companies(shipment_city=shipment_city)
    
    return jsonify({
        "success": True if companies else False,
        "data": companies or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/logistic/shipment/terminal-tc/addresses')
def get_terminal_addresses():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipment_city', 'Красноярск')
    
    addresses = ocs_api.get_terminal_addresses(shipment_city=shipment_city)
    
    return jsonify({
        "success": True if addresses else False,
        "data": addresses or [],
        "source": "ocs_api"
    })

# Shipments endpoints
@app.route('/api/v2/shipments/stock', methods=['POST'])
def create_shipment_stock():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    shipment = ocs_api.create_shipment_stock(shipment_data=data)
    
    return jsonify({
        "success": True if shipment else False,
        "data": shipment or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/pickup-point', methods=['POST'])
def create_shipment_pickup_point():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    shipment = ocs_api.create_shipment_pickup_point(shipment_data=data)
    
    return jsonify({
        "success": True if shipment else False,
        "data": shipment or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/direct', methods=['POST'])
def create_shipment_direct():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    shipment = ocs_api.create_shipment_direct(shipment_data=data)
    
    return jsonify({
        "success": True if shipment else False,
        "data": shipment or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/terminal-tc', methods=['POST'])
def create_shipment_terminal_tc():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    shipment = ocs_api.create_shipment_terminal_tc(shipment_data=data)
    
    return jsonify({
        "success": True if shipment else False,
        "data": shipment or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/<shipment_id>')
def get_shipment(shipment_id):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment = ocs_api.get_shipment(shipment_id=shipment_id)
    
    return jsonify({
        "success": True if shipment else False,
        "data": shipment or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/<shipment_id>/serial-numbers')
def get_shipment_serial_numbers(shipment_id):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    serial_numbers = ocs_api.get_shipment_serial_numbers(shipment_id=shipment_id)
    
    return jsonify({
        "success": True if serial_numbers else False,
        "data": serial_numbers or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/stock/dates', methods=['POST'])
def get_stock_dates():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    dates = ocs_api.get_stock_dates(lines_data=data)
    
    return jsonify({
        "success": True if dates else False,
        "data": dates or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/pickup-point/dates', methods=['POST'])
def get_pickup_point_dates():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    dates = ocs_api.get_pickup_point_dates(dates_data=data)
    
    return jsonify({
        "success": True if dates else False,
        "data": dates or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/direct/dates', methods=['POST'])
def get_direct_dates():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    dates = ocs_api.get_direct_dates(dates_data=data)
    
    return jsonify({
        "success": True if dates else False,
        "data": dates or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/direct/cost', methods=['POST'])
def get_direct_cost():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    cost = ocs_api.get_direct_cost(cost_data=data)
    
    return jsonify({
        "success": True if cost else False,
        "data": cost or {},
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/terminal-tc/dates', methods=['POST'])
def get_terminal_tc_dates():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    dates = ocs_api.get_terminal_tc_dates(dates_data=data)
    
    return jsonify({
        "success": True if dates else False,
        "data": dates or [],
        "source": "ocs_api"
    })

@app.route('/api/v2/shipments/terminal-tc/cost', methods=['POST'])
def get_terminal_tc_cost():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Неверный формат данных"}), 400
    
    cost = ocs_api.get_terminal_tc_cost(cost_data=data)
    
    return jsonify({
        "success": True if cost else False,
        "data": cost or {},
        "source": "ocs_api"
    })

# Invoices endpoints
@app.route('/api/v2/invoices')
def get_invoices():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    from_date = request.args.get('From')
    to_date = request.args.get('To')
    
    invoices = ocs_api.get_invoices(from_date=from_date, to_date=to_date)
    
    return jsonify({
        "success": True if invoices else False,
        "data": invoices or [],
        "source": "ocs_api"
    })

# Reports endpoints
@app.route('/api/v2/reports/orders')
def get_orders_report():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    report = ocs_api.get_orders_report()
    
    return jsonify({
        "success": True if report else False,
        "data": report or [],
        "source": "ocs_api"
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)