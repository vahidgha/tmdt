"""کدهای بازیابی رمز عبور روی دیتابیس — امن برای اجرای چند-worker.

جایگزین دیکشنری درون‌حافظه‌ای که با gunicorn چند-process به‌درستی کار نمی‌کرد.
"""
import secrets
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

TTL_MINUTES = 5


def _clear(db_session, identifier: str) -> None:
    from .models import PasswordResetCode
    (db_session.query(PasswordResetCode)
     .filter_by(identifier=identifier).delete(synchronize_session=False))


def _purge_expired(db_session) -> None:
    from .models import PasswordResetCode
    (db_session.query(PasswordResetCode)
     .filter(PasswordResetCode.expires_at < datetime.utcnow())
     .delete(synchronize_session=False))


def create_code(db_session, identifier: str, user_id: int) -> str:
    """یک کد ۶ رقمی جدید می‌سازد، کدهای قبلی این شناسه را پاک و ذخیره می‌کند."""
    from .models import PasswordResetCode
    _purge_expired(db_session)
    _clear(db_session, identifier)
    code = str(secrets.randbelow(900000) + 100000)
    db_session.add(PasswordResetCode(
        identifier=identifier,
        code_hash=generate_password_hash(code),
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(minutes=TTL_MINUTES),
    ))
    db_session.commit()
    return code


def _active(db_session, identifier: str):
    from .models import PasswordResetCode
    return (db_session.query(PasswordResetCode)
            .filter(PasswordResetCode.identifier == identifier,
                    PasswordResetCode.expires_at >= datetime.utcnow())
            .order_by(PasswordResetCode.created_at.desc())
            .first())


def verify_code(db_session, identifier: str, code: str) -> bool:
    """کد را بررسی و در صورت درستی، رکورد را verified می‌کند."""
    rec = _active(db_session, identifier)
    if not rec or not check_password_hash(rec.code_hash, code):
        return False
    rec.verified = True
    db_session.commit()
    return True


def verified_user_id(db_session, identifier: str):
    """اگر کد فعال و verified باشد، user_id را برمی‌گرداند؛ در غیر این‌صورت None."""
    rec = _active(db_session, identifier)
    return rec.user_id if rec and rec.verified else None


def consume(db_session, identifier: str) -> None:
    """پس از استفاده موفق، کد را حذف می‌کند."""
    _clear(db_session, identifier)
    db_session.commit()
