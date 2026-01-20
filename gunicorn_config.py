# Gunicorn конфигурация для Render.com
import multiprocessing
import os

# Количество воркеров (оптимально для free плана на Render)
workers = 2  # Можно увеличить до 4, если приложение позволяет

# Биндинг
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# Тип воркеров
worker_class = 'sync'  # Для Render лучше использовать sync

# Таймауты
timeout = 120  # 120 секунд для медленных запросов
keepalive = 5

# Перезагрузка воркеров
max_requests = 1000
max_requests_jitter = 50

# Логирование
accesslog = '-'  # stdout
errorlog = '-'   # stdout
loglevel = 'info'

# Предзагрузка приложения для ускорения запуска
preload_app = True

# Размер буфера
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# Улучшения производительности
worker_connections = 1000