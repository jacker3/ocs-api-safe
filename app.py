import os
import requests
import logging
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import functools
import json

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Простой кэш в памяти
cache = {}

def cache_response(ttl_seconds=300):
    """Декоратор для кэширования ответов"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Проверяем кэш
            if cache_key in cache:
                cached_data, timestamp = cache[cache_key]
                if datetime.now() - timestamp < timedelta(seconds=ttl_seconds):
                    logger.info(f"Cache hit for {cache_key}")
                    return cached_data
            
            # Выполняем функцию
            result = func(*args, **kwargs)
            
            # Сохраняем в кэш
            cache[cache_key] = (result, datetime.now())
            logger.info(f"Cached response for {cache_key}")
            
            return result
        return wrapper
    return decorator

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
        # Используем тестовую среду для разработки
        self.base_url = os.getenv('OCS_API_URL', 'https://connector.b2b.ocs.ru/api/v2')
        self.session = requests.Session()
        self.session.headers.update({
            'accept': 'application/json',
            'X-API-Key': self.api_key,
            'User-Agent': 'OCS-Integration/1.0'
        })
        # Настройки сессии с увеличенными таймаутами
        self.session.mount('https://', requests.adapters.HTTPAdapter(
            max_retries=2,
            pool_connections=20,
            pool_maxsize=20,
            pool_block=True
        ))
    
    def _make_request(self, endpoint: str, params=None, method='GET', data=None, timeout=None):
        """Базовый метод для выполнения запросов к OCS API"""
        try:
            url = f"{self.base_url}/{endpoint}"
            logger.info(f"OCS API: {method} {url}")
            
            if params:
                logger.debug(f"Params: {params}")
            if data and method in ['POST', 'PUT']:
                logger.debug(f"Data size: {len(json.dumps(data) if data else 0)} bytes")
            
            # Увеличенные таймауты для медленных запросов OCS
            if timeout is None:
                # Категории могут быть очень большими, нужен большой таймаут
                if 'catalog/categories' in endpoint:
                    timeout = (60, 300)  # 60 сек на соединение, 300 на чтение
                else:
                    timeout = (30, 120)  # 30 сек на соединение, 120 на чтение
            
            start_time = time.time()
            
            if method == 'GET':
                response = self.session.get(url, params=params, timeout=timeout, verify=True)
            elif method == 'POST':
                response = self.session.post(url, params=params, json=data, timeout=timeout, verify=True)
            elif method == 'PUT':
                response = self.session.put(url, params=params, json=data, timeout=timeout, verify=True)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params, timeout=timeout, verify=True)
            elif method == 'HEAD':
                response = self.session.head(url, params=params, timeout=timeout, verify=True)
            else:
                logger.error(f"Unsupported method: {method}")
                return None
            
            elapsed = time.time() - start_time
            logger.info(f"OCS API response time: {elapsed:.2f}s, Status: {response.status_code}, Size: {len(response.content) if response.content else 0} bytes")
            
            if response.status_code == 200:
                if method == 'HEAD':
                    return {"success": True, "headers": dict(response.headers)}
                try:
                    return response.json()
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}, Response: {response.text[:200]}")
                    return {"error": "Invalid JSON response", "code": 500}
            elif response.status_code == 204:
                return {"success": True}
            elif response.status_code == 429:
                logger.error("Превышен лимит запросов (429)")
                return {"error": "Rate limit exceeded", "code": 429}
            elif response.status_code == 401:
                logger.error("Неавторизованный запрос (401)")
                return {"error": "Unauthorized", "code": 401}
            elif response.status_code == 403:
                logger.error("Доступ запрещен (403)")
                return {"error": "Forbidden", "code": 403}
            elif response.status_code == 404:
                logger.error("Не найдено (404)")
                return {"error": "Not found", "code": 404}
            else:
                logger.error(f"OCS API Error {response.status_code}: {response.text[:200]}")
                return {"error": f"OCS API returned {response.status_code}", "code": response.status_code}
                
        except requests.exceptions.Timeout:
            logger.error(f"OCS API Timeout: {url}")
            return {"error": "Timeout connecting to OCS API", "code": 408}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"OCS API Connection Error: {url} - {str(e)}")
            return {"error": f"Connection error: {str(e)}", "code": 503}
        except requests.exceptions.RequestException as e:
            logger.error(f"OCS API Request Exception: {url} - {str(e)}")
            return {"error": f"Request exception: {str(e)}", "code": 500}
        except Exception as e:
            logger.error(f"OCS API Exception: {e}")
            return {"error": str(e), "code": 500}

    # ===== КАТАЛОГ (Catalog) =====
    
    @cache_response(ttl_seconds=3600)  # 1 час для категорий
    def get_categories(self):
        """2.2.1 Получение информации о товарных категориях"""
        # Для категорий используем специальный увеличенный таймаут
        return self._make_request("catalog/categories", timeout=(60, 300))
    
    def get_products_by_category(self, categories: str, shipment_city: str, **params):
        """2.2.2 Получение информации о состоянии склада и ценах по товарным категориям"""
        endpoint = f"catalog/categories/{categories}/products"
        params = params.copy() if params else {}
        params['shipmentcity'] = shipment_city
        
        # Установка значений по умолчанию согласно документации
        default_params = {
            'onlyavailable': 'false',
            'includeregular': 'true',
            'includesale': 'false',
            'includeuncondition': 'false',
            'includeunconditionalimages': 'false',
            'includemissing': 'false',
            'withdescriptions': 'true'
        }
        
        for key, value in default_params.items():
            if key not in params:
                params[key] = value
        
        return self._make_request(endpoint, params=params, timeout=(30, 180))
    
    def get_products_by_category_batch(self, categories_list: list, shipment_city: str, **params):
        """2.2.3 Batch-версия для большого количества категорий"""
        endpoint = "catalog/categories/batch/products"
        params = params.copy() if params else {}
        params['shipmentcity'] = shipment_city
        
        # Установка значений по умолчанию
        default_params = {
            'onlyavailable': 'false',
            'includeregular': 'true',
            'withdescriptions': 'true'
        }
        
        for key, value in default_params.items():
            if key not in params:
                params[key] = value
        
        data = categories_list
        return self._make_request(endpoint, params=params, method='POST', data=data, timeout=(30, 180))
    
    def get_products_by_ids(self, item_ids: str, shipment_city: str, **params):
        """2.2.4 Получение информации по списку товаров"""
        endpoint = f"catalog/products/{item_ids}"
        params = params.copy() if params else {}
        params['shipmentcity'] = shipment_city
        return self._make_request(endpoint, params=params, timeout=(30, 120))
    
    def get_products_by_ids_batch(self, item_ids_list: list, shipment_city: str, **params):
        """2.2.5 Batch-версия для большого количества товаров"""
        endpoint = "catalog/products/batch"
        params = params.copy() if params else {}
        params['shipmentcity'] = shipment_city
        data = item_ids_list
        return self._make_request(endpoint, params=params, method='POST', data=data, timeout=(30, 180))
    
    def get_certificates(self, item_ids: str, actuality: str = "actual"):
        """2.2.6 Получение информации о сертификатах"""
        endpoint = f"catalog/products/{item_ids}/certificates"
        params = {'actuality': actuality}
        return self._make_request(endpoint, params=params, timeout=(30, 120))
    
    def get_certificates_batch(self, item_ids_list: list, actuality: str = "actual"):
        """2.2.7 Batch-версия сертификатов"""
        endpoint = "catalog/products/batch/certificates"
        params = {'actuality': actuality}
        data = item_ids_list
        return self._make_request(endpoint, params=params, method='POST', data=data, timeout=(30, 180))
    
    # ===== СПРАВОЧНАЯ ИНФОРМАЦИЯ =====
    
    @cache_response(ttl_seconds=3600)
    def get_shipment_cities(self):
        """2.3.1 Получение информации о допустимых городах отгрузки"""
        return self._make_request("logistic/shipment/cities", timeout=(30, 120))
    
    def get_stock_locations(self, shipment_city: str):
        """2.3.2 Получение информации о допустимых местоположениях товара"""
        endpoint = "logistic/stocks/locations"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params, timeout=(30, 120))
    
    # ===== КОНТЕНТ (Content) =====
    
    def get_content(self, item_ids: str):
        """3.2.1 Получение характеристик товара"""
        endpoint = f"content/{item_ids}"
        return self._make_request(endpoint)
    
    def get_content_batch(self, item_ids_list: list):
        """3.2.2 Batch-версия характеристик товара"""
        endpoint = "content/batch"
        data = item_ids_list
        return self._make_request(endpoint, method='POST', data=data)
    
    def get_content_changes(self, from_date: str):
        """3.2.3 Получение списка товаров с изменениями в контенте"""
        endpoint = "content/changes"
        params = {'from': from_date}
        return self._make_request(endpoint, params=params)
    
    def get_image_info(self, image_type: str, file_name: str):
        """HEAD-запрос для проверки изображений"""
        endpoint = f"files/{image_type}/{file_name}"
        return self._make_request(endpoint, method='HEAD')
    
    def get_original_image(self, file_name: str):
        """Получение оригинального изображения"""
        endpoint = f"files/contentimages/{file_name}"
        return self._make_request(endpoint)
    
    def get_medium_image(self, file_name: str):
        """Получение уменьшенного изображения (800x800)"""
        endpoint = f"files/mediumimages/{file_name}"
        return self._make_request(endpoint)
    
    # ===== ЗАКАЗЫ (Orders) =====
    
    def create_order(self, order_data: dict, async_mode: bool = True):
        """4.2.1 Создание заказа"""
        endpoint = "orders" if async_mode else "orders/online"
        return self._make_request(endpoint, method='POST', data=order_data)
    
    def update_order(self, order_id: str, order_data: dict, async_mode: bool = True):
        """4.2.2 Редактирование заказа"""
        endpoint = f"orders/{order_id}" if async_mode else f"orders/online/{order_id}"
        return self._make_request(endpoint, method='PUT', data=order_data)
    
    def cancel_order_reserves(self, order_id: str, async_mode: bool = True):
        """4.2.3 Отмена резервов по заказу"""
        endpoint = f"orders/{order_id}" if async_mode else f"orders/online/{order_id}"
        return self._make_request(endpoint, method='DELETE')
    
    def get_order(self, order_id: str):
        """4.2.4 Получение информации о заказе"""
        endpoint = f"orders/{order_id}"
        return self._make_request(endpoint)
    
    def get_orders(self, from_date: str, to_date: str, only_active: bool = True):
        """4.2.5 Получение списка созданных заказов"""
        endpoint = "orders"
        params = {
            'From': from_date,
            'To': to_date,
            'OnlyActive': 'true' if only_active else 'false'
        }
        return self._make_request(endpoint, params=params)
    
    def transfer_lines_to_manager(self, transfer_data: dict, async_mode: bool = True):
        """4.2.6 Передача строк заказов под управление менеджеру"""
        endpoint = "orders/lines/transfer-to-manager" if async_mode else "orders/online/lines/transfer-to-manager"
        return self._make_request(endpoint, method='POST', data=transfer_data)
    
    def get_order_operation_status(self, operation_id: str):
        """4.2.7 Получение информации о выполнении асинхронной операции"""
        endpoint = f"orders/operations/{operation_id}"
        return self._make_request(endpoint)
    
    def sync_order(self, order_id: str, sync_data: dict, async_mode: bool = True):
        """4.2.8 Синхронизация заказа"""
        endpoint = f"orders/{order_id}/sync" if async_mode else f"orders/online/{order_id}/sync"
        return self._make_request(endpoint, method='PUT', data=sync_data)
    
    # ===== СПРАВОЧНАЯ ИНФОРМАЦИЯ ДЛЯ ЗАКАЗОВ =====
    
    def get_payers(self):
        """4.3.1 Получение информации о плательщиках"""
        return self._make_request("account/payers")
    
    def get_contact_persons(self):
        """4.3.2 Получение информации о контактных лицах"""
        return self._make_request("account/contactpersons")
    
    def get_reserve_places(self):
        """4.3.4 Получение информации о разрешенных местах резервирования"""
        return self._make_request("logistic/stocks/reserveplaces")
    
    def get_currency_exchanges(self):
        """4.3.5 Получение курсов валют"""
        return self._make_request("account/currencies/exchanges")
    
    # ===== СЧЕТА (Invoices) =====
    
    def get_invoices(self, from_date: str, to_date: str):
        """5.2.1 Получение списка счетов"""
        endpoint = "invoices"
        params = {'From': from_date, 'To': to_date}
        return self._make_request(endpoint, params=params)
    
    def export_invoice_pdf(self, invoice_id: str):
        """5.2.2 Экспорт счета в PDF"""
        endpoint = f"invoices/{invoice_id}.pdf"
        return self._make_request(endpoint)
    
    # ===== ОТЧЕТЫ (Reports) =====
    
    def get_orders_report(self):
        """6.2.1 Отчет Состояние заказов"""
        return self._make_request("reports/orders")
    
    # ===== ОТГРУЗКИ (Shipments) =====
    
    def create_shipment_stock(self, shipment_data: dict):
        """7.2.1 Отгрузка со склада (самовывоз)"""
        return self._make_request("shipments/stock", method='POST', data=shipment_data)
    
    def create_shipment_pickup_point(self, shipment_data: dict):
        """7.2.2 Отгрузка с доставкой до пункта выдачи"""
        return self._make_request("shipments/pickup-point", method='POST', data=shipment_data)
    
    def create_shipment_direct(self, shipment_data: dict):
        """7.2.3 Отгрузка с доставкой до адреса"""
        return self._make_request("shipments/direct", method='POST', data=shipment_data)
    
    def create_shipment_terminal_tc(self, shipment_data: dict):
        """7.2.4 Отгрузка с доставкой до терминала ТК"""
        return self._make_request("shipments/terminal-tc", method='POST', data=shipment_data)
    
    def get_shipment(self, shipment_id: str):
        """7.2.5 Получение информации по отгрузке"""
        endpoint = f"shipments/{shipment_id}"
        return self._make_request(endpoint)
    
    def get_shipment_dates_stock(self, lines_data: list):
        """7.3.1 Получение информации по допустимому времени отгрузки с самовывозом"""
        endpoint = "shipments/stock/dates"
        data = {"lines": lines_data}
        return self._make_request(endpoint, method='POST', data=data)
    
    def get_shipment_dates_pickup_point(self, shipment_city: str, pickup_point_id: str, lines_data: list):
        """7.3.2 Получение информации по доступным датам доставки (до пункта выдачи)"""
        endpoint = "shipments/pickup-point/dates"
        data = {
            "shipmentCity": shipment_city,
            "pickupPoint": pickup_point_id,
            "lines": lines_data
        }
        return self._make_request(endpoint, method='POST', data=data)
    
    def get_partner_finances(self):
        """7.3.3 Получение информации по кредитным средствам партнёра"""
        return self._make_request("account/finances")
    
    def get_consignees(self):
        """7.3.4 Получение информации о грузополучателях"""
        return self._make_request("account/consignees")
    
    def get_pickup_points(self, shipment_city: str):
        """7.3.5 Получение информации о пунктах выдачи"""
        endpoint = "logistic/shipment/pickup-points"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    def get_delivery_cost_direct(self, lines_data: list, shipment_city: str, delivery_address: str, delivery_date: str = None):
        """7.3.6 Получение информации о стоимости доставки до адреса"""
        endpoint = "shipments/direct/cost"
        data = {
            "lines": lines_data,
            "shipmentCity": shipment_city,
            "deliveryAddress": delivery_address
        }
        if delivery_date:
            data["deliveryDate"] = delivery_date
        return self._make_request(endpoint, method='POST', data=data)
    
    def get_delivery_dates_direct(self, lines_data: list, delivery_address_id: str):
        """7.3.7 Получение информации по доступным датам доставки (до адреса)"""
        endpoint = "shipments/direct/dates"
        data = {
            "lines": lines_data,
            "deliveryAddressId": delivery_address_id
        }
        return self._make_request(endpoint, method='POST', data=data)
    
    def get_delivery_addresses(self, shipment_city: str):
        """7.3.8 Получение списка зарегистрированных доступных адресов доставки"""
        endpoint = "logistic/shipment/delivery-addresses"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    def get_shipment_serial_numbers(self, shipment_id: str):
        """7.3.9 Получение серийных номеров строк отгрузки"""
        endpoint = f"shipments/{shipment_id}/serial-numbers"
        return self._make_request(endpoint)
    
    def get_transport_companies(self, shipment_city: str):
        """7.3.10 Получение списка доступных транспортных компаний"""
        endpoint = "logistic/shipment/terminal-tc/transport-companies"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    def get_terminal_addresses(self, shipment_city: str):
        """7.3.11 Получение списка зарегистрированных адресов доставки (до терминала ТК)"""
        endpoint = "logistic/shipment/terminal-tc/addresses"
        params = {'shipmentcity': shipment_city}
        return self._make_request(endpoint, params=params)
    
    def get_delivery_dates_terminal_tc(self, lines_data: list, delivery_address_id: str):
        """7.3.12 Получение информации по доступным датам доставки (до терминала ТК)"""
        endpoint = "shipments/terminal-tc/dates"
        data = {
            "lines": lines_data,
            "deliveryAddressId": delivery_address_id
        }
        return self._make_request(endpoint, method='POST', data=data)
    
    def get_delivery_cost_terminal_tc(self, lines_data: list, delivery_address_id: str, delivery_date: str = None):
        """7.3.13 Получение информации о стоимости доставки до терминала ТК"""
        endpoint = "shipments/terminal-tc/cost"
        data = {
            "lines": lines_data,
            "deliveryAddressId": delivery_address_id
        }
        if delivery_date:
            data["deliveryDate"] = delivery_date
        return self._make_request(endpoint, method='POST', data=data)

# Инициализация API
api_key = os.getenv('OCS_API_KEY')
if not api_key:
    logger.warning("OCS_API_KEY not found in environment variables")
    ocs_api = None
else:
    logger.info(f"API key loaded, length: {len(api_key)}")
    ocs_api = OCSAPI(api_key=api_key)

# ===== АСИНХРОННАЯ ОБРАБОТКА ДЛЯ ДЛИННЫХ ЗАПРОСОВ =====

import threading
from queue import Queue

# Очередь для асинхронных задач
task_queue = Queue()
results_cache = {}

def worker():
    """Фоновый воркер для обработки длинных запросов"""
    while True:
        try:
            task_id, func, args, kwargs = task_queue.get()
            logger.info(f"Processing task {task_id}")
            
            try:
                result = func(*args, **kwargs)
                results_cache[task_id] = {
                    'status': 'completed',
                    'result': result,
                    'timestamp': datetime.now().isoformat()
                }
            except Exception as e:
                results_cache[task_id] = {
                    'status': 'error',
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
            
            task_queue.task_done()
        except Exception as e:
            logger.error(f"Worker error: {e}")

# Запускаем воркер в фоновом потоке
worker_thread = threading.Thread(target=worker, daemon=True)
worker_thread.start()

def submit_async_task(func, *args, **kwargs):
    """Отправка задачи в фоновый воркер"""
    task_id = f"task_{int(time.time())}_{id(func)}"
    task_queue.put((task_id, func, args, kwargs))
    return task_id

# ===== FLASK ЭНДПОИНТЫ С УЛУЧШЕННОЙ ОБРАБОТКОЙ =====

@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "OCS B2B API Proxy Service v2",
        "version": "2.0.0",
        "api_key_configured": bool(api_key),
        "timestamp": datetime.now().isoformat(),
        "features": [
            "Batch-обработка больших объемов данных",
            "Кэширование справочной информации",
            "Увеличенные таймауты для медленных запросов",
            "Асинхронная обработка длинных операций"
        ],
        "timeout_settings": {
            "categories": "60s connect, 300s read",
            "products": "30s connect, 180s read",
            "default": "30s connect, 120s read"
        }
    })

@app.route('/api/v2/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "OCS API Proxy",
        "cache_size": len(cache),
        "async_queue_size": task_queue.qsize(),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/test')
def test_api():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    # Тестируем только быстрые эндпоинты
    cities_result = ocs_api.get_shipment_cities()
    
    cities_success = cities_result and "error" not in cities_result
    
    return jsonify({
        "success": cities_success,
        "api_key_configured": True,
        "endpoints": {
            "cities": {
                "success": cities_success,
                "error": cities_result.get("error") if not cities_success else None
            }
        },
        "timestamp": datetime.now().isoformat(),
        "note": "Categories endpoint is heavy and may timeout in test"
    })

# ===== КАТАЛОГ С АСИНХРОННОЙ ОБРАБОТКОЙ =====

@app.route('/api/v2/catalog/categories')
def get_categories_route():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    # Проверяем, не запрашивает ли клиент асинхронный режим
    async_mode = request.args.get('async', 'false').lower() == 'true'
    
    if async_mode:
        # Асинхронный режим - возвращаем task_id сразу
        task_id = submit_async_task(ocs_api.get_categories)
        return jsonify({
            "success": True,
            "async": True,
            "task_id": task_id,
            "message": "Задача запущена в фоновом режиме",
            "status_url": f"/api/v2/tasks/{task_id}"
        })
    
    # Синхронный режим (может таймаутить)
    try:
        result = ocs_api.get_categories()
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result or [],
            "cached": True,
            "async": False,
            "count": len(result) if isinstance(result, list) else 0
        })
            
    except Exception as e:
        logger.error(f"Error in get_categories: {e}")
        # Предлагаем клиенту использовать асинхронный режим
        return jsonify({
            "success": False,
            "error": str(e),
            "suggestion": "Use ?async=true for heavy requests",
            "async_url": f"{request.path}?async=true"
        }), 500

@app.route('/api/v2/logistic/shipment/cities')
def get_cities_route():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    try:
        result = ocs_api.get_shipment_cities()
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result or [],
            "cached": True
        })
            
    except Exception as e:
        logger.error(f"Error in get_cities: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/v2/catalog/categories/<path:category>/products')
def get_products_by_category_route(category):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipmentcity = request.args.get('shipmentcity', 'Москва')
    async_mode = request.args.get('async', 'false').lower() == 'true'
    
    # Обработка специальных значений
    if category in ['undefined', 'null', '']:
        category = 'all'
    
    try:
        # Собираем все параметры из запроса
        params = request.args.to_dict()
        
        # Удаляем shipmentcity из params, т.к. он передается отдельно
        if 'shipmentcity' in params:
            shipmentcity = params.pop('shipmentcity')
        
        # Удаляем async флаг
        if 'async' in params:
            params.pop('async')
        
        if async_mode and category == 'all':
            # Для всех категорий используем асинхронный режим
            task_id = submit_async_task(
                ocs_api.get_products_by_category,
                category, shipmentcity, **params
            )
            return jsonify({
                "success": True,
                "async": True,
                "task_id": task_id,
                "message": "Задача запущена в фоновом режиме",
                "status_url": f"/api/v2/tasks/{task_id}"
            })
        
        result = ocs_api.get_products_by_category(
            categories=category,
            shipmentcity=shipmentcity,
            **params
        )
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result or {"result": []},
            "total_count": len(result.get('result', [])) if result else 0,
            "async": False
        })
            
    except Exception as e:
        logger.error(f"Error in get_products_by_category: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "suggestion": "For large requests use ?async=true"
        }), 500

# ===== АСИНХРОННЫЕ ТАСКИ =====

@app.route('/api/v2/tasks/<task_id>')
def get_task_status(task_id):
    """Получение статуса асинхронной задачи"""
    if task_id in results_cache:
        result = results_cache[task_id]
        
        # Очищаем старые результаты (старше 1 часа)
        if datetime.now() - datetime.fromisoformat(result['timestamp']) > timedelta(hours=1):
            results_cache.pop(task_id, None)
            return jsonify({
                "success": False,
                "error": "Task expired",
                "task_id": task_id
            }), 404
        
        if result['status'] == 'completed':
            response_data = {
                "success": True,
                "task_id": task_id,
                "status": "completed",
                "timestamp": result['timestamp'],
                "result": result['result']
            }
            # Можно удалить результат после получения
            # results_cache.pop(task_id, None)
            return jsonify(response_data)
        elif result['status'] == 'error':
            return jsonify({
                "success": False,
                "task_id": task_id,
                "status": "error",
                "error": result['error'],
                "timestamp": result['timestamp']
            }), 500
    
    # Проверяем, есть ли задача в очереди
    # Простая проверка - если task_id не в кэше, значит задача еще в процессе
    return jsonify({
        "success": True,
        "task_id": task_id,
        "status": "processing",
        "queue_position": "unknown",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/catalog/categories/batch/products', methods=['POST'])
def get_products_by_category_batch_route():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    try:
        data = request.get_json()
        if not data or 'categories' not in data:
            return jsonify({"success": False, "error": "Необходим массив categories в теле запроса"}), 400
        
        categories_list = data['categories']
        shipment_city = data.get('shipmentcity', 'Москва')
        params = data.get('params', {})
        
        # Используем функцию для обработки больших объемов
        if len(categories_list) > 50:
            result = get_categories_products_batch_all(categories_list, shipment_city, **params)
        else:
            result = ocs_api.get_products_by_category_batch(categories_list, shipment_city, **params)
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result,
            "total_count": result.get('total_count', len(result.get('result', []))) if result else 0
        })
            
    except Exception as e:
        logger.error(f"Error in get_products_by_category_batch: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/v2/catalog/products/<path:item_ids>')
def get_products_by_ids_route(item_ids):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipmentcity = request.args.get('shipmentcity', 'Москва')
    
    try:
        # Собираем все параметры из запроса
        params = request.args.to_dict()
        
        # Удаляем shipmentcity из params, т.к. он передается отдельно
        if 'shipmentcity' in params:
            shipmentcity = params.pop('shipmentcity')
        
        result = ocs_api.get_products_by_ids(
            item_ids=item_ids,
            shipmentcity=shipmentcity,
            **params
        )
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result or {"result": []},
            "total_count": len(result.get('result', [])) if result else 0
        })
            
    except Exception as e:
        logger.error(f"Error in get_products_by_ids: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/v2/catalog/products/batch', methods=['POST'])
def get_products_by_ids_batch_route():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    try:
        data = request.get_json()
        if not data or 'items' not in data:
            return jsonify({"success": False, "error": "Необходим массив items в теле запроса"}), 400
        
        items_list = data['items']
        shipment_city = data.get('shipmentcity', 'Москва')
        params = data.get('params', {})
        
        # Используем функцию для обработки больших объемов
        if len(items_list) > 100:
            result = get_products_by_ids_batch_all(items_list, shipment_city, **params)
        else:
            result = ocs_api.get_products_by_ids_batch(items_list, shipment_city, **params)
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result,
            "total_count": result.get('total_count', len(result.get('result', []))) if result else 0
        })
            
    except Exception as e:
        logger.error(f"Error in get_products_by_ids_batch: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/v2/catalog/products/<path:item_ids>/certificates')
def get_certificates_route(item_ids):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    actuality = request.args.get('actuality', 'actual')
    
    try:
        result = ocs_api.get_certificates(item_ids, actuality)
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result or {"result": []}
        })
            
    except Exception as e:
        logger.error(f"Error in get_certificates: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/v2/catalog/products/batch/certificates', methods=['POST'])
def get_certificates_batch_route():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    try:
        data = request.get_json()
        if not data or 'items' not in data:
            return jsonify({"success": False, "error": "Необходим массив items в теле запроса"}), 400
        
        items_list = data['items']
        actuality = data.get('actuality', 'actual')
        
        # Разбиваем на батчи для больших объемов
        all_certificates = []
        for batch in batch_process_items(items_list, batch_size=100):
            result = ocs_api.get_certificates_batch(batch, actuality)
            
            if result and "error" not in result:
                batch_certificates = result.get('result', [])
                all_certificates.extend(batch_certificates)
                time.sleep(0.1)
            else:
                logger.error(f"Ошибка в batch-запросе сертификатов: {result.get('error')}")
        
        return jsonify({
            "success": True,
            "data": {"result": all_certificates},
            "total_count": len(all_certificates)
        })
            
    except Exception as e:
        logger.error(f"Error in get_certificates_batch: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ===== СПРАВОЧНАЯ ИНФОРМАЦИЯ =====

@app.route('/api/v2/logistic/stocks/locations')
def get_stock_locations_route():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    shipment_city = request.args.get('shipmentcity', 'Москва')
    
    try:
        result = ocs_api.get_stock_locations(shipment_city)
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result or []
        })
            
    except Exception as e:
        logger.error(f"Error in get_stock_locations: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ===== КОНТЕНТ =====

@app.route('/api/v2/content/<path:item_ids>')
def get_content_route(item_ids):
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    try:
        result = ocs_api.get_content(item_ids)
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result or {"result": []}
        })
            
    except Exception as e:
        logger.error(f"Error in get_content: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/v2/content/batch', methods=['POST'])
def get_content_batch_route():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    try:
        data = request.get_json()
        if not data or 'items' not in data:
            return jsonify({"success": False, "error": "Необходим массив items в теле запроса"}), 400
        
        items_list = data['items']
        
        # Разбиваем на батчи для больших объемов
        all_content = []
        for batch in batch_process_items(items_list, batch_size=100):
            result = ocs_api.get_content_batch(batch)
            
            if result and "error" not in result:
                batch_content = result.get('result', [])
                all_content.extend(batch_content)
                time.sleep(0.1)
            else:
                logger.error(f"Ошибка в batch-запросе контента: {result.get('error')}")
        
        return jsonify({
            "success": True,
            "data": {"result": all_content},
            "total_count": len(all_content)
        })
            
    except Exception as e:
        logger.error(f"Error in get_content_batch: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/v2/content/changes')
def get_content_changes_route():
    if not ocs_api:
        return jsonify({"success": False, "error": "API ключ не настроен"}), 500
    
    from_date = request.args.get('from')
    if not from_date:
        return jsonify({"success": False, "error": "Необходим параметр from"}), 400
    
    try:
        result = ocs_api.get_content_changes(from_date)
        
        if result and "error" in result:
            return jsonify({
                "success": False,
                "error": result.get("error"),
                "code": result.get("code", 500)
            }), result.get("code", 500)
        
        return jsonify({
            "success": True,
            "data": result or []
        })
            
    except Exception as e:
        logger.error(f"Error in get_content_changes: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ===== ОТЛАДОЧНЫЕ ЭНДПОИНТЫ =====

@app.route('/api/v2/debug/cache')
def debug_cache():
    """Эндпоинт для отладки кэша"""
    cache_info = []
    for key, (value, timestamp) in cache.items():
        age = datetime.now() - timestamp
        cache_info.append({
            "key": key[:50] + "..." if len(key) > 50 else key,
            "age_seconds": age.total_seconds(),
            "type": type(value).__name__,
            "has_error": isinstance(value, dict) and "error" in value
        })
    
    return jsonify({
        "cache_size": len(cache),
        "cache_entries": cache_info,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/v2/debug/clear-cache')
def clear_cache():
    """Очистка кэша"""
    global cache
    old_size = len(cache)
    cache.clear()
    
    return jsonify({
        "success": True,
        "message": "Cache cleared",
        "cleared_entries": old_size,
        "timestamp": datetime.now().isoformat()
    })

# ===== УТИЛИТЫ =====

@app.route('/api/v2/utils/batch-split', methods=['POST'])
def batch_split():
    """Утилита для разбиения большого списка на батчи"""
    try:
        data = request.get_json()
        if not data or 'items' not in data:
            return jsonify({"success": False, "error": "Необходим массив items"}), 400
        
        items = data['items']
        batch_size = data.get('batch_size', 100)
        
        batches = list(batch_process_items(items, batch_size))
        
        return jsonify({
            "success": True,
            "total_items": len(items),
            "batch_size": batch_size,
            "batches_count": len(batches),
            "batches": batches
        })
            
    except Exception as e:
        logger.error(f"Error in batch_split: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/v2/debug/status')
def debug_status():
    """Расширенный статус сервиса"""
    return jsonify({
        "service": "OCS API Proxy",
        "timestamp": datetime.now().isoformat(),
        "cache": {
            "size": len(cache),
            "keys": list(cache.keys())[:5] + ["..."] if len(cache) > 5 else list(cache.keys())
        },
        "async": {
            "queue_size": task_queue.qsize(),
            "results_cache_size": len(results_cache),
            "worker_alive": worker_thread.is_alive()
        },
        "ocs_api": {
            "configured": bool(ocs_api),
            "base_url": ocs_api.base_url if ocs_api else None
        },
        "timeouts": {
            "categories": "60s/300s",
            "products": "30s/180s",
            "default": "30s/120s"
        }
    })
    
@app.route('/api/v2/utils/batch-status')
def batch_status():
    """Статус batch-обработки"""
    return jsonify({
        "success": True,
        "status": "active",
        "max_batch_size": {
            "categories": 50,
            "products": 100,
            "certificates": 100,
            "content": 100
        },
        "recommendations": [
            "Используйте batch-методы для больших объемов данных",
            "Разбивайте списки на батчи по 50-100 элементов",
            "Добавляйте задержки между batch-запросами",
            "Кэшируйте справочную информацию"
        ]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    # Для разработки используем debug сервер с большими таймаутами
    if os.environ.get('FLASK_ENV') == 'development':
        logger.info("Running in development mode with increased timeouts")
        app.run(host='0.0.0.0', port=port, debug=True, threaded=True)
    else:
        # Для production нужно настроить Gunicorn с правильными параметрами
        logger.info(f"Starting server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False)