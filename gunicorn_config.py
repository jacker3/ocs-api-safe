# gunicorn_config.py
import multiprocessing

# Безопасные настройки для Render
timeout = 30  # 30 секунд - короткий таймаут
keepalive = 5
worker_class = 'sync'
workers = 2  # Минимум воркеров для free плана
bind = '0.0.0.0:10000'
preload_app = True  # Предзагрузка приложения