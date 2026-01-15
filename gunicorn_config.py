# gunicorn_config.py
import multiprocessing

# Увеличиваем таймаут для медленных запросов к OCS
timeout = 120  # 120 секунд (2 минуты)
keepalive = 65
worker_class = 'sync'
workers = 2
bind = '0.0.0.0:10000'
preload_app = True