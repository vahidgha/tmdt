"""ابزارهای کمکی HTTP — پارس درخواست، guard های دسترسی و لاگ فعالیت"""
from flask import jsonify, request
from flask_login import current_user

from ..constants import Role


def require_admin():
    """
    اگر کاربر جاری ادمین نباشد، یک پاسخ ۴۰۳ برمی‌گرداند؛ در غیر این صورت None.

    استفاده:
        err = require_admin()
        if err: return err
    """
    if current_user.role != Role.ADMIN:
        return jsonify(error="دسترسی ندارید."), 403
    return None


def require_finance():
    """دسترسی بخش مالی — ادمین یا مسئول مالی مجازند."""
    if current_user.role not in (Role.ADMIN, Role.FINANCE):
        return jsonify(error="دسترسی ندارید."), 403
    return None


def has_finance_access() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.FINANCE)


def get_request_body() -> dict:
    """
    بدنه درخواست را به‌صورت dict برمی‌گرداند.
    هم JSON و هم form-data را پشتیبانی می‌کند.
    """
    if request.is_json:
        return request.get_json(silent=True, force=True) or {}
    return request.form.to_dict()


def get_field(key: str, default: str = "") -> str:
    """مقدار یک فیلد از بدنه درخواست را برمی‌گرداند."""
    return get_request_body().get(key, default) or default


def parse_int(value, default: int = 0) -> int:
    """تبدیل ایمن به عدد صحیح."""
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def log_activity(action: str, detail: str = None, category: str = "general", user=None):
    """
    یک رکورد فعالیت در جدول activity_logs ثبت می‌کند.
    در صورت بروز خطا، transaction جاری را rollback نمی‌کند — فقط flush ناموفق را.
    """
    # import داخلی برای جلوگیری از circular import
    from .. import db_session
    from ..models import ActivityLog

    try:
        actor = user or current_user
        uid   = actor.id if actor.is_authenticated else None
        entry = ActivityLog(
            user_id=uid,
            action=action,
            category=category,
            detail=detail,
            ip=request.remote_addr,
        )
        db_session.add(entry)
        db_session.flush()
    except Exception:
        db_session.rollback()
