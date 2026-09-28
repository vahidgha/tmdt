"""اکستنشن‌های Flask — جدا از factory برای جلوگیری از circular import"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect

csrf = CSRFProtect()

# بدون محدودیت سراسری — فقط endpoint های حساس decorate می‌شوند
# برای deploy چند-worker از storage اشتراکی (مثل Redis) با env var
# RATELIMIT_STORAGE_URI استفاده کنید.
import os
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'),
)
