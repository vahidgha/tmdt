"""سرویس پیامک SMS.ir — ارسال کد تأیید (OTP) و پیامک عادی

توکن API با این اولویت خوانده می‌شود:
  1. env var: SMSIR_API_KEY
  2. تنظیمات سایت (SiteSetting): sms_api_key

تنظیمات دیگر (از پنل ادمین):
  sms_template_id — شناسه قالب «ارسال سریع» ساخته‌شده در پنل sms.ir
                    (قالب باید پارامتری با نام CODE داشته باشد)
  sms_line_number — شماره خط برای ارسال پیامک عادی (اختیاری)
"""
import logging
import os

import requests as _req

log = logging.getLogger(__name__)

BASE_URL = "https://api.sms.ir/v1"
TIMEOUT  = 10


def _setting(db_session, key: str) -> str:
    try:
        from .models import SiteSetting
        row = db_session.get(SiteSetting, key)
        return row.value.strip() if row and row.value else ""
    except Exception:
        return ""


def _api_key(db_session=None) -> str:
    key = os.environ.get("SMSIR_API_KEY", "").strip()
    if key:
        return key
    if db_session is not None:
        return _setting(db_session, "sms_api_key")
    return ""


def send_verify_code(mobile: str, code: str, db_session=None) -> bool:
    """
    ارسال کد تأیید با «ارسال سریع» (verify send) — نیازی به خط اختصاصی ندارد.
    قالب باید در پنل sms.ir ساخته شده و شناسه آن در تنظیمات ذخیره شود.

    Returns: True اگر ارسال موفق بود.
    """
    api_key = _api_key(db_session)
    if not api_key:
        log.warning("SMS.ir: API key تنظیم نشده — پیامک ارسال نشد")
        return False

    template_id = _setting(db_session, "sms_template_id") if db_session is not None else ""
    template_id = os.environ.get("SMSIR_TEMPLATE_ID", "").strip() or template_id
    if not template_id:
        # اگر قالب تنظیم نشده اما خط پیامک موجود است، کد را به‌صورت پیام عادی بفرست
        log.warning("SMS.ir: شناسه قالب تنظیم نشده — تلاش برای ارسال با خط عادی")
        return send_message(mobile, f"کد بازیابی رمز عبور شما: {code}\nاین کد ۵ دقیقه اعتبار دارد.", db_session)

    try:
        r = _req.post(
            f"{BASE_URL}/send/verify",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={
                "mobile": mobile,
                "templateId": int(template_id),
                "parameters": [{"name": "CODE", "value": str(code)}],
            },
            timeout=TIMEOUT,
        )
        data = r.json() if r.content else {}
        ok = r.ok and data.get("status") == 1
        if not ok:
            log.warning("SMS.ir verify error %s: %s", r.status_code, str(data)[:300])
        return ok
    except Exception as e:
        log.error("SMS.ir: خطا در ارسال کد تأیید: %s", e)
        return False


def send_message(mobile: str, text: str, db_session=None) -> bool:
    """ارسال پیامک عادی (bulk با یک گیرنده) — نیاز به شماره خط دارد."""
    api_key = _api_key(db_session)
    if not api_key:
        log.warning("SMS.ir: API key تنظیم نشده — پیامک ارسال نشد")
        return False

    line = _setting(db_session, "sms_line_number") if db_session is not None else ""
    line = os.environ.get("SMSIR_LINE_NUMBER", "").strip() or line
    if not line:
        log.warning("SMS.ir: شماره خط (sms_line_number) تنظیم نشده")
        return False

    try:
        r = _req.post(
            f"{BASE_URL}/send/bulk",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"lineNumber": int(line), "messageText": text, "mobiles": [mobile]},
            timeout=TIMEOUT,
        )
        data = r.json() if r.content else {}
        ok = r.ok and data.get("status") == 1
        if not ok:
            log.warning("SMS.ir bulk error %s: %s", r.status_code, str(data)[:300])
        return ok
    except Exception as e:
        log.error("SMS.ir: خطا در ارسال پیامک: %s", e)
        return False


def get_credit(db_session=None):
    """اعتبار باقی‌مانده پنل را برمی‌گرداند (None در صورت خطا)."""
    api_key = _api_key(db_session)
    if not api_key:
        return None
    try:
        r = _req.get(f"{BASE_URL}/credit",
                     headers={"x-api-key": api_key}, timeout=TIMEOUT)
        data = r.json()
        return data.get("data") if r.ok and data.get("status") == 1 else None
    except Exception:
        return None
