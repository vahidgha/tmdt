"""مسیرهای احراز هویت — ورود/خروج، بازیابی رمز با OTP، تکمیل پروفایل اولیه، اسلایدهای صفحه ورود."""
import random
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from urllib.parse import urlparse

from .. import db_session
from ..extensions import limiter
from ..models import ActivityLog, SiteSetting, Slide, User
from .. import bot, sms
from .. import otp as otp_store

bp = Blueprint('auth', __name__)


CAPTCHA_AFTER_FAILS = 3   # بعد از این تعداد رمز اشتباه، کپچا الزامی می‌شود


def _login_ctx():
    """تنظیمات سایت + اسلایدهای فعال — برای پس‌زمینه اسلایدر صفحه ورود."""
    settings = {r.key: r.value for r in db_session.query(SiteSetting).all()}
    slides = db_session.query(Slide).filter_by(active=True).order_by(Slide.order).all()
    return {'settings': settings, 'login_slides': slides}


def _new_captcha():
    """یک کپچای ریاضی ساده می‌سازد و پاسخ را در session ذخیره می‌کند."""
    a, b = random.randint(2, 9), random.randint(2, 9)
    session['captcha_answer'] = str(a + b)
    return f'{a} + {b} = ?'


def _captcha_required() -> bool:
    return session.get('login_fails', 0) >= CAPTCHA_AFTER_FAILS


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'],
               error_message='تلاش‌های زیاد — لطفاً یک دقیقه صبر کنید.')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # بررسی کپچا (اگر بعد از ۳ تلاش ناموفق فعال شده باشد)
        if _captcha_required():
            answer   = request.form.get('captcha', '').strip()
            expected = session.pop('captcha_answer', None)
            if not expected or answer != expected:
                error = 'پاسخ سؤال امنیتی اشتباه است.'
                captcha_q = _new_captcha()
                return render_template('auth/login.html', error=error, captcha_q=captcha_q, **_login_ctx())

        user = db_session.query(User).filter_by(username=username).first()

        if not user or not check_password_hash(user.password_hash, password):
            session['login_fails'] = session.get('login_fails', 0) + 1
            error = 'نام کاربری یا رمز عبور اشتباه است.'
            db_session.add(ActivityLog(action='login_fail', category='auth',
                detail=f'نام کاربری: {username}', ip=request.remote_addr))
            db_session.commit()
        elif not user.active:
            error = 'این حساب غیرفعال شده است. با مدیر تماس بگیرید.'
        else:
            session.pop('login_fails', None)
            session.pop('captcha_answer', None)
            session.permanent = True
            login_user(user, remember=False)
            db_session.add(ActivityLog(user_id=user.id, action='login', category='auth',
                detail=None, ip=request.remote_addr))
            db_session.commit()
            next_url = request.args.get('next') or ''
            # prevent open redirect: only allow relative (on-site) URLs
            if next_url and urlparse(next_url).netloc:
                next_url = ''
            return redirect(next_url or url_for('dashboard.home'))

    captcha_q = _new_captcha() if _captcha_required() else None
    return render_template('auth/login.html', error=error, captcha_q=captcha_q, **_login_ctx())


def _send_otp_for(nat: str) -> bool:
    """کد تأیید را برای شناسه (کد ملی/نام کاربری/موبایل) داده‌شده می‌سازد و ارسال می‌کند."""
    user = (db_session.query(User).filter_by(national_code=nat).first()
            or db_session.query(User).filter_by(username=nat).first()
            or db_session.query(User).filter_by(phone=nat).first())
    if not user or (not user.phone and not user.bale_chat_id):
        return False

    otp = otp_store.create_code(db_session, nat, user.id)

    # اولویت ۱: پیامک (sms.ir) — اولویت ۲: ربات بله
    sent = False
    if user.phone:
        sent = sms.send_verify_code(user.phone, otp, db_session)
    if not sent and user.bale_chat_id:
        sent = bot.send(user.bale_chat_id,
            f'🔐 *کد بازیابی رمز عبور*\n\nکد شما: `{otp}`\n\nاین کد ۵ دقیقه اعتبار دارد.',
            db_session)
    if not sent:
        otp_store.consume(db_session, nat)
    return sent


@bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'],
               error_message='تلاش‌های زیاد — لطفاً یک دقیقه صبر کنید.')
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))

    error = None
    success = None

    if request.method == 'POST':
        nat = request.form.get('national_code', '').strip()
        # نرمال‌سازی ارقام فارسی — جستجو با کد ملی، نام کاربری یا شماره موبایل
        nat = nat.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))

        # پاسخ برای شناسه موجود/ناموجود و با/بدون شماره تماس عمداً یکسان است —
        # در غیر این‌صورت مهاجم می‌تواند با امتحان کردن کدهای ملی مختلف
        # بفهمد کدام‌ها در سامانه ثبت‌شده‌اند (User Enumeration). صفحه تأیید
        # کد هم برای شناسه ناموجود، فقط «کد اشتباه» نشان می‌دهد (چون هرگز
        # کدی برایش ساخته نشده)، پس این مسیر برای هر دو حالت امن است.
        _send_otp_for(nat)
        session['otp_nat'] = nat
        return redirect(url_for('auth.verify_otp'))

    return render_template('auth/forgot_password.html', error=error, success=success)


@bp.route('/resend-otp', methods=['POST'])
@limiter.limit('3 per 5 minutes',
               error_message='تعداد درخواست ارسال مجدد بیش از حد است — کمی صبر کنید.')
def resend_otp():
    """ارسال دوباره کد تأیید برای همان درخواست بازیابی رمز جاری (بدون نیاز به وارد کردن مجدد کد ملی)."""
    nat = session.get('otp_nat')
    if not nat:
        return jsonify(error='درخواست بازیابی معتبر یافت نشد — دوباره تلاش کنید.'), 400
    if _send_otp_for(nat):
        return jsonify(ok=True)
    return jsonify(error='ارسال کد با خطا مواجه شد. لطفاً بعداً تلاش کنید.'), 400


@bp.route('/verify-otp', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'],
               error_message='تلاش‌های زیاد — لطفاً یک دقیقه صبر کنید.')
def verify_otp():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))

    nat = session.get('otp_nat')
    if not nat:
        return redirect(url_for('auth.forgot_password'))

    error = None

    if request.method == 'POST':
        entered = request.form.get('otp', '').strip()
        if otp_store.verify_code(db_session, nat, entered):
            session['otp_verified'] = nat
            return redirect(url_for('auth.reset_password'))
        else:
            error = 'کد وارد شده اشتباه یا منقضی شده است.'

    return render_template('auth/verify_otp.html', error=error)


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))

    nat = session.get('otp_verified')
    uid = otp_store.verified_user_id(db_session, nat) if nat else None
    if not uid:
        return redirect(url_for('auth.forgot_password'))

    error = None

    if request.method == 'POST':
        pw1 = request.form.get('password', '')
        pw2 = request.form.get('password2', '')
        if len(pw1) < 6:
            error = 'رمز عبور باید حداقل ۶ کاراکتر باشد.'
        elif pw1 != pw2:
            error = 'رمز عبور و تکرار آن یکسان نیستند.'
        else:
            user = db_session.get(User, uid)
            if user:
                user.password_hash = generate_password_hash(pw1)
                db_session.commit()
            otp_store.consume(db_session, nat)
            session.pop('otp_nat', None)
            session.pop('otp_verified', None)
            return redirect(url_for('auth.login') + '?msg=password_reset')

    return render_template('auth/reset_password.html', error=error)


@bp.route('/logout')
@login_required
def logout():
    db_session.add(ActivityLog(user_id=current_user.id, action='logout', category='auth',
                               ip=request.remote_addr))
    db_session.commit()
    logout_user()
    return redirect(url_for('public.index'))
