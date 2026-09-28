"""API ماژول ربات بله"""
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from ... import bot, db_session
from ...extensions import limiter
from ...models import Notification, User
from ...utils.http import get_request_body, require_admin

bp = Blueprint("bale", __name__)

LINK_CODE_TTL_MINUTES = 15


@bp.post("/bale/webhook")
@limiter.limit('60 per minute')
def bale_webhook():
    """
    دریافت و پردازش آپدیت‌های webhook ربات بله.
    این مسیر عمومی و بدون احراز هویت است (پیام‌های واقعی از سرور بله می‌آیند)؛
    محدودیت نرخ فقط برای جلوگیری از brute-force کد پیوند ۶ رقمی توسط یک
    مهاجم است — دفاع اصلی، منقضی‌شدن کد پس از چند دقیقه است (پایین را ببینید).
    """
    from flask import request
    update = request.get_json(silent=True) or {}
    bot.handle_update(update, db_session)
    return jsonify(ok=True)


@bp.get("/bale/link-code")
@login_required
def bale_link_code():
    """تولید کد ۶ رقمی یک‌بارمصرف برای اتصال حساب بله — با انقضای کوتاه‌مدت."""
    code = str(secrets.randbelow(900000) + 100000)
    current_user.bale_link_code = code
    current_user.bale_link_code_expires_at = datetime.utcnow() + timedelta(minutes=LINK_CODE_TTL_MINUTES)
    db_session.commit()
    return jsonify(code=code, ttl_minutes=LINK_CODE_TTL_MINUTES)


@bp.get("/bale/status")
@login_required
def bale_status():
    """وضعیت اتصال بله کاربر جاری"""
    return jsonify(
        linked=bool(current_user.bale_chat_id),
        bale_chat_id=current_user.bale_chat_id or "",
    )


@bp.post("/bale/unlink")
@login_required
def bale_unlink():
    """قطع اتصال حساب بله از کاربر جاری"""
    current_user.bale_chat_id   = None
    current_user.bale_link_code = None
    db_session.commit()
    return jsonify(ok=True)


@bp.post("/bale/set-webhook")
@login_required
def bale_set_webhook():
    """تنظیم خودکار webhook ربات بله روی دامنه فعلی سایت (فقط ادمین)"""
    from flask import request
    err = require_admin()
    if err: return err

    webhook_url = f"https://{request.host}/api/bale/webhook"
    result = bot.set_webhook(webhook_url, db_session)
    if result.get("ok"):
        return jsonify(ok=True, webhook=webhook_url)
    return jsonify(error=f"خطا در تنظیم webhook: {result.get('description', 'نامشخص')}",
                   webhook=webhook_url), 400


@bp.get("/bale/webhook-info")
@login_required
def bale_webhook_info():
    """وضعیت webhook فعلی ربات (فقط ادمین)"""
    err = require_admin()
    if err: return err
    return jsonify(bot.get_webhook_info(db_session))


@bp.post("/bale/broadcast")
@login_required
def bale_broadcast():
    """ارسال پیام انبوه به همه اعضای متصل به بله"""
    err = require_admin()
    if err: return err

    data = get_request_body()
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(error="متن پیام الزامی است."), 400

    bot.notify_all_members(text, db_session)
    members = db_session.query(User).filter_by(role="member", active=True).all()
    for m in members:
        db_session.add(Notification(
            user_id=m.id,
            title=data.get("title", "پیام هیئت"),
            body=text,
            type="info",
        ))
    db_session.commit()
    return jsonify(ok=True, sent=len(members))
