"""ربات بله — اطلاع‌رسانی سامانه تعاونی مسکن"""
import os, logging
import requests as _req

log = logging.getLogger(__name__)

# آدرس رسمی API بله (tapi.ir اشتباه بود و باعث کار نکردن ربات می‌شد)
BASE = 'https://tapi.bale.ai/bot{token}/{method}'


# ── توکن ─────────────────────────────────────────────────────────────────────

def _token(db_session=None) -> str:
    """توکن را از env یا دیتابیس برمی‌گرداند."""
    token = os.environ.get('BALE_TOKEN', '').strip()
    if token:
        return token
    if db_session:
        try:
            from .models import SiteSetting
            row = db_session.get(SiteSetting, 'bale_bot_token')
            if row and row.value.strip():
                return row.value.strip()
        except Exception:
            pass
    return ''


# ── ارسال پیام ───────────────────────────────────────────────────────────────

def send(chat_id: str, text: str, db_session=None, parse_mode: str = 'Markdown') -> bool:
    """ارسال پیام به یک chat_id."""
    token = _token(db_session)
    if not token:
        log.warning('توکن ربات بله تنظیم نشده — پیام ارسال نشد')
        return False
    try:
        url = BASE.format(token=token, method='sendMessage')
        r = _req.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}, timeout=8)
        if not r.ok:
            log.warning('Bale API error %s: %s', r.status_code, r.text[:200])
        return r.ok
    except Exception as e:
        log.error('خطا در ارسال پیام بله: %s', e)
        return False


def send_all(chat_ids: list, text: str, db_session=None) -> int:
    """ارسال پیام به لیستی از chat_id ها. تعداد موفق را برمی‌گرداند."""
    sent = 0
    for cid in chat_ids:
        if cid and send(cid, text, db_session):
            sent += 1
    return sent


# ── اطلاع‌رسانی ───────────────────────────────────────────────────────────────

def notify_user(user, text: str, db_session=None) -> bool:
    """ارسال پیام به یک کاربر (اگر بله وصل کرده باشد)."""
    if user and user.bale_chat_id:
        return send(user.bale_chat_id, text, db_session)
    return False


def notify_admins(text: str, db_session) -> None:
    """ارسال پیام به همه ادمین‌هایی که بله وصل کرده‌اند."""
    from .models import User
    admins = db_session.query(User).filter_by(role='admin', active=True).all()
    send_all([u.bale_chat_id for u in admins if u.bale_chat_id], text, db_session)


def notify_all_members(text: str, db_session) -> int:
    """ارسال پیام به همه اعضای فعالی که بله وصل کرده‌اند. تعداد ارسال را برمی‌گرداند."""
    from .models import User
    users = db_session.query(User).filter(
        User.active == True,
        User.bale_chat_id != None,
        User.bale_chat_id != '',
    ).all()
    return send_all([u.bale_chat_id for u in users], text, db_session)


# ── مدیریت webhook ────────────────────────────────────────────────────────────

def set_webhook(webhook_url: str, db_session=None) -> dict:
    """
    webhook ربات را روی آدرس دادهشده تنظیم می‌کند.
    خروجی: dict شامل ok و در صورت خطا description.
    """
    token = _token(db_session)
    if not token:
        return {'ok': False, 'description': 'توکن ربات تنظیم نشده است.'}
    try:
        url = BASE.format(token=token, method='setWebhook')
        r = _req.post(url, json={'url': webhook_url}, timeout=10)
        data = r.json() if r.content else {}
        return {'ok': bool(data.get('ok')), 'description': data.get('description', ''),
                'status_code': r.status_code}
    except Exception as e:
        log.error('خطا در تنظیم webhook بله: %s', e)
        return {'ok': False, 'description': str(e)}


def get_webhook_info(db_session=None) -> dict:
    """اطلاعات webhook فعلی ربات را برمی‌گرداند."""
    token = _token(db_session)
    if not token:
        return {'ok': False, 'description': 'توکن ربات تنظیم نشده است.'}
    try:
        url = BASE.format(token=token, method='getWebhookInfo')
        r = _req.get(url, timeout=10)
        return r.json() if r.content else {'ok': False}
    except Exception as e:
        return {'ok': False, 'description': str(e)}

def handle_update(update: dict, db_session) -> None:
    """پردازش پیام ورودی از webhook بله."""
    msg     = update.get('message', {})
    chat_id = str(msg.get('chat', {}).get('id', ''))
    text    = (msg.get('text') or '').strip()

    if not chat_id or not text:
        return

    def reply(t):
        send(chat_id, t, db_session)

    # کد ۶ رقمی پیوند
    if text.isdigit() and len(text) == 6:
        _link_account(chat_id, text, db_session, reply)
        return

    # /start [code]
    if text.startswith('/start'):
        parts = text.split()
        code  = parts[1] if len(parts) > 1 else ''
        if code and code.isdigit() and len(code) == 6:
            _link_account(chat_id, code, db_session, reply)
        else:
            reply(_welcome_text())
        return

    # /status
    if text == '/status':
        from .models import User
        user = db_session.query(User).filter_by(bale_chat_id=chat_id).first()
        if user:
            reply(
                f'✅ *حساب شما متصل است*\n\n'
                f'👤 نام: {user.full_name}\n'
                f'🆔 کد ملی: {user.national_code or "—"}\n'
                f'📱 موبایل: {user.phone or "—"}'
            )
        else:
            reply(
                '❌ حساب شما هنوز متصل نیست.\n\n'
                'برای اتصال، کد ۶ رقمی را از پنل کاربری دریافت و اینجا ارسال کنید.'
            )
        return

    # /unlink
    if text == '/unlink':
        from .models import User
        user = db_session.query(User).filter_by(bale_chat_id=chat_id).first()
        if user:
            user.bale_chat_id = None
            db_session.commit()
            reply('🔓 حساب شما با موفقیت از سامانه جدا شد.\nبرای اتصال مجدد، کد جدیدی از پنل دریافت کنید.')
        else:
            reply('⚠️ هیچ حسابی به این چت متصل نیست.')
        return

    # /help یا هر پیام دیگه
    reply(_welcome_text())


def _link_account(chat_id: str, code: str, db_session, reply) -> None:
    """
    پیوند حساب کاربری با chat_id بله.

    نکته امنیتی: این وبهوک عمومی و بدون احراز هویت است — هر کسی می‌تواند مستقیم
    به آن درخواست بزند و کد را حدس بزند. تنها سدِ واقعی در برابر brute-force
    کدِ ۶ رقمی، انقضای کوتاه‌مدت آن است؛ کدهای بدون تاریخ انقضا (رکوردهای قدیمی
    از قبل این رفع) هم به‌طور محافظه‌کارانه نامعتبر در نظر گرفته می‌شوند.
    """
    from datetime import datetime
    from .models import User

    user = db_session.query(User).filter_by(bale_link_code=code).first()
    if not user or not user.bale_link_code_expires_at or user.bale_link_code_expires_at < datetime.utcnow():
        reply(
            '❌ *کد نامعتبر یا منقضی شده*\n\n'
            'کدها ۱۵ دقیقه اعتبار دارند.\n'
            'از پنل کاربری یک کد جدید دریافت کنید.'
        )
        return

    # اگه این chat_id قبلاً به حساب دیگه‌ای وصل بود، جدا کن
    existing = db_session.query(User).filter_by(bale_chat_id=chat_id).first()
    if existing and existing.id != user.id:
        existing.bale_chat_id = None

    user.bale_chat_id   = chat_id
    user.bale_link_code = None
    user.bale_link_code_expires_at = None
    db_session.commit()

    reply(
        f'✅ *اتصال با موفقیت انجام شد!*\n\n'
        f'👤 {user.full_name} عزیز، خوش آمدید.\n\n'
        f'از این پس پیام‌های زیر برای شما ارسال می‌شود:\n'
        f'• اطلاعیه‌های جدید\n'
        f'• وضعیت درخواست‌های انتقال\n'
        f'• تأیید یا رد پرداخت‌ها\n'
        f'• پاسخ تیکت‌های پشتیبانی\n\n'
        f'برای مشاهده وضعیت: /status\n'
        f'برای قطع اتصال: /unlink'
    )


def _welcome_text() -> str:
    return (
        '👋 *سلام! به ربات سامانه تعاونی مسکن خوش آمدید.*\n\n'
        'برای دریافت اطلاع‌رسانی‌ها، حساب خود را متصل کنید:\n\n'
        '۱. وارد پنل کاربری شوید\n'
        '۲. به بخش *ربات بله* بروید\n'
        '۳. کد ۶ رقمی دریافت کرده و اینجا ارسال کنید\n\n'
        'دستورات:\n'
        '• /status — وضعیت اتصال\n'
        '• /unlink — قطع اتصال'
    )
