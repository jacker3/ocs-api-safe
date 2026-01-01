import multiprocessing

# Количество воркеров
workers = 2  # Меньше воркеров для экономии памяти

# Таймауты
timeout = 30  # 30 секунд (увеличено для медленных запросов)
keepalive = 2

# Логирование
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Перезапуск при ошибках
max_requests = 1000
max_requests_jitter = 50