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
# اپ (و کارهای یک‌باره‌اش هنگام بوت: create_all/migrate/seed) فقط یک‌بار در
# master بارگذاری می‌شود، نه یک‌بار به‌ازای هر worker — بدون این، چند worker
# هم‌زمان روی یک دیتابیس SQLite تازه برای ساخت جدول‌ها با هم رقابت می‌کنند و
# کرش می‌کنند (race condition دقیقاً همینجا)
preload_app = True
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


def post_fork(server, worker):
    """
    با preload_app، اتصال دیتابیس در master قبل از fork ساخته شده — استفاده از
    همان اتصال به‌ارث‌رسیده بین چند پردازش امن نیست (به‌خصوص SQLite). هر worker
    بلافاصله بعد از fork، pool را dispose می‌کند تا در اولین استفاده، اتصال
    تازه‌ی خودش را بسازد.
    """
    from app import db_session
    if db_session is not None:
        db_session.remove()
        db_session.bind.dispose()
