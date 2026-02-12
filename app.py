import os
import requests
import logging
from flask import Flask, Response, request, g
from flask_cors import CORS
from dotenv import load_dotenv
import sys
import time

# Минимальное логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)
CORS(app)

# Базовые настройки
OCS_BASE_URL = "https://connector.b2b.ocs.ru/api/v2"
API_KEY = os.getenv('OCS_API_KEY')

# Простой сессионный объект
session = requests.Session()
if API_KEY:
    session.headers.update({
        'accept': 'application/json',
        'X-API-Key': API_KEY,
        'User-Agent': 'OCS-Raw-Proxy/1.0'
    })
    logger.info(f"API ключ загружен, длина: {len(API_KEY)}")
else:
    logger.warning("API ключ не найден!")

@app.before_request
def log_request():
    """Минимальное логирование"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    logger.info(f"{request.method} {request.path} от {client_ip}")

@app.route('/')
def home():
    """Простая главная страница"""
    return {
        "status": "online",
        "service": "OCS Raw Proxy",
        "message": "Просто передает запросы к OCS API без обработки",
        "endpoints": [
            "/api/categories",
            "/api/cities",
            "/api/products/category?category=all",
            "/api/products/search?q=test",
            "/api/health"
        ]
    }

@app.route('/api/health')
def health_check():
    """Health check для Railway"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "port": int(os.getenv('PORT', 8000))
    }, 200

@app.route('/api/<path:endpoint>')
def proxy_request(endpoint):
    """Прокси-запрос к OCS API"""
    try:
        params = dict(request.args)
        ocs_url = f"{OCS_BASE_URL}/{endpoint}"
        logger.info(f"Проксируем к: {ocs_url}")
        logger.info(f"Параметры: {params}")
        
        response = session.get(
            ocs_url,
            params=params,
            timeout=(5, 15),
            allow_redirects=True
        )
        
        logger.info(f"Ответ OCS: {response.status_code}")
        
        return Response(
            response=response.content,
            status=response.status_code,
            headers=dict(response.headers),
            content_type=response.headers.get('content-type', 'application/json')
        )
        
    except requests.exceptions.Timeout:
        logger.error("Таймаут запроса к OCS API")
        return {"error": "Timeout connecting to OCS API"}, 504
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Ошибка подключения к OCS API: {e}")
        return {"error": "Cannot connect to OCS API"}, 502
    except Exception as e:
        logger.error(f"Ошибка: {type(e).__name__}: {str(e)}")
        return {"error": f"Proxy error: {str(e)}"}, 500

@app.route('/api/categories')
def get_categories_raw():
    """Специальный эндпоинт для категорий"""
    return proxy_request('catalog/categories')

@app.route('/api/cities')
def get_cities_raw():
    """Специальный эндпоинт для городов"""
    return proxy_request('logistic/shipment/cities')

if __name__ == '__main__':
    # Railway автоматически назначает PORT, используем его
    port = int(os.getenv('PORT', 8000))
    logger.info(f"Запуск RAW прокси на порту {port}")
    logger.info(f"API Key присутствует: {bool(API_KEY)}")
    
    # Важно: host='0.0.0.0' для доступа извне
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=False, 
        threaded=True,
        use_reloader=False
    )
