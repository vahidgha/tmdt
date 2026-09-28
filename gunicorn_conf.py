"""پیکربندی Gunicorn برای اجرای production.

اجرا:
  gunicorn -c gunicorn_conf.py run:app

متغیرهای محیطی مؤثر:
  WEB_CONCURRENCY  تعداد worker (پیش‌فرض: 2×CPU+1)
  BIND             آدرس bind (پیش‌فرض: 127.0.0.1:8000)
"""
import multiprocessing
import os

bind = os.environ.get("BIND", "127.0.0.1:8000")
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1000          # ری‌استارت دوره‌ای worker برای جلوگیری از نشت حافظه
max_requests_jitter = 100
accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")   # - یعنی stdout
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "-")
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# نکته: چون rate-limit و OTP روی دیتابیس هستند، چند worker بی‌مشکل کار می‌کند.
# برای rate-limit در مقیاس بالا، RATELIMIT_STORAGE_URI=redis://... را ست کنید.
