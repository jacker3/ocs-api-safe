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
        # Увеличиваем таймауты для сессии
        self.timeout = (60, 300)  # 60 сек на соединение, 300 на чтение (5 минут)
    
    def get_categories(self):
        """Получение категорий с увеличенными таймаутами"""
        url = f'{BASE_URL}/catalog/categories'
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()  # Проверяем статус ответа
            return response.json()
        except requests.exceptions.Timeout:
            return {'error': 'Request timeout - OCS API is too slow'}
        except requests.exceptions.RequestException as e:
            return {'error': f'Request failed: {str(e)}'}
        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}'}

# Инициализация клиента
client = OCSClient() if API_KEY else None

def build_category_tree(categories):
    """Преобразует плоский список категорий в древовидную структуру"""
    if not categories:
        return []
    
    # Создаем словарь для быстрого доступа к категориям по коду
    category_dict = {}
    for category in categories:
        category_dict[category['category']] = {
            'category': category['category'],
            'name': category['name'],
            'children': []
        }
    
    # Строим дерево
    tree = []
    for category in categories:
        # Если у категории есть родитель (определяется по коду)
        # В документации указано, что структура уже древовидная
        # Проверяем, является ли это корневым элементом
        if 'parent' not in category or not category.get('parent'):
            # Добавляем корневые категории
            tree.append(category_dict[category['category']])
    
    return tree

@app.route('/')
def home():
    return jsonify({
        'service': 'OCS Categories API',
        'endpoints': ['/categories'],
        'api_key_configured': bool(API_KEY),
        'note': 'Categories endpoint may take several minutes to load'
    })

@app.route('/categories')
def get_categories():
    if not client:
        return jsonify({'error': 'API key not configured'}), 500
    
    result = client.get_categories()
    
    if 'error' in result:
        return jsonify(result), 500
    
    # Согласно документации, API возвращает уже древовидную структуру
    # Проверяем, есть ли поле 'children' в ответе
    if isinstance(result, dict) and 'children' in result:
        # Если ответ - это один объект с children
        return jsonify(result)
    elif isinstance(result, list):
        # Если ответ - это список категорий, строим дерево
        tree = build_category_tree(result)
        return jsonify(tree)
    else:
        # Возвращаем как есть
        return jsonify(result)

@app.route('/health')
def health():
    """Простая проверка здоровья"""
    return jsonify({'status': 'ok', 'api_configured': bool(API_KEY)})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    # Запуск с увеличенными настройками
    app.run(host='0.0.0.0', port=port, threaded=True)