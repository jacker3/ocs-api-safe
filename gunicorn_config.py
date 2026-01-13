import multiprocessing

# Количество воркеров
workers = multiprocessing.cpu_count() * 2 + 1

# Увеличенные таймауты для медленных запросов OCS
timeout = 300  # 5 минут
keepalive = 5

# Пул воркеров
worker_class = 'sync'  # или 'gevent' для асинхронности
worker_connections = 1000

# Перезапуск воркеров при утечке памяти
max_requests = 1000
max_requests_jitter = 50

# Логирование
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Увеличенный размер буфера для больших ответов
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190