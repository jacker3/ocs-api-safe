# gunicorn_config.py
import multiprocessing

# Настройки для увеличения таймаутов
timeout = 300  # 5 минут
keepalive = 65
worker_class = 'sync'
workers = multiprocessing.cpu_count() * 2 + 1
bind = '0.0.0.0:10000'