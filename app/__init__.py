"""نقطه ورود اصلی برنامه Flask — create_app() اپ را می‌سازد: دیتابیس، لاگین، امنیت
(CSRF/Rate-Limit/هدرهای امنیتی)، ثبت تمام Blueprintها، هندلرهای خطا (403/404/500)
و لاگ‌گیری خطا/اطلاع‌رسانی به ادمین از طریق بله را در یک‌جا پیکربندی می‌کند."""
import os, secrets
from datetime import timedelta
from flask import Flask, session, redirect, url_for, request, render_template
from flask_login import LoginManager, logout_user, current_user
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from .models import Base, User, SiteSetting, ActivityLog

login_manager = LoginManager()
db_session    = None


def _setup_error_logging(app):
    """لاگ چرخشی روی فایل logs/app.log برای خطاهای سطح WARNING به بالا."""
    import logging
    from logging.handlers import RotatingFileHandler

    log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(log_dir, 'app.log'),
            maxBytes=2 * 1024 * 1024, backupCount=5, encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s [%(name)s] %(message)s'))
        handler.setLevel(logging.WARNING)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
    except Exception:
        pass  # اگر نوشتن فایل ممکن نبود، لاگ به stderr می‌رود


def _notify_admins_error(exc):
    """پیام کوتاه خطای ۵۰۰ را به ادمین‌های متصل به بله می‌فرستد (best-effort)."""
    try:
        from . import bot
        from .models import User
        admins = (db_session.query(User)
                  .filter(User.role == 'admin', User.active == True,
                          User.bale_chat_id != None, User.bale_chat_id != '')
                  .all())
        if not admins:
            return
        text = (f'🛑 *خطای سرور*\n\nمسیر: `{request.path}`\n'
                f'نوع: {type(exc).__name__}\nپیام: {str(exc)[:200]}')
        for a in admins:
            bot.send(a.bale_chat_id, text, db_session)
    except Exception:
        pass


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
    )
    _secret = os.environ.get('SECRET_KEY')
    if not _secret:
        import warnings
        warnings.warn(
            "SECRET_KEY env var is not set — user sessions will reset on every restart. "
            "Set SECRET_KEY in production.",
            RuntimeWarning, stacklevel=2,
        )
    app.secret_key = _secret or secrets.token_hex(32)

    # با چند worker (gunicorn) و بدون storage اشتراکی (Redis)، هر worker
    # شمارنده rate-limit جدای خودش را دارد — یعنی محدودیت مؤثر (مثلاً روی
    # فرم ورود) عملاً به‌اندازه تعداد worker ضعیف‌تر از مقدار تنظیم‌شده است.
    # env var ممکن است با کامنت نادرست (بدون فاصله قبل از #) ست شده باشد
    # (مثلاً "1# توضیح") — به‌جای کرش کل اپ روی مقدار پیش‌فرض امن fallback می‌کنیم
    _workers_raw = (os.environ.get('WEB_CONCURRENCY', '1') or '1').split('#', 1)[0].strip()
    try:
        _workers = int(_workers_raw)
    except ValueError:
        _workers = 1
    if _workers > 1 and not os.environ.get('RATELIMIT_STORAGE_URI'):
        import warnings
        warnings.warn(
            f"WEB_CONCURRENCY={_workers} ولی RATELIMIT_STORAGE_URI تنظیم نشده — "
            "هر worker شمارنده rate-limit جدا دارد و محدودیت‌های ضدحمله brute-force "
            f"(مثلاً ورود) عملاً تا {_workers} برابر ضعیف‌تر می‌شوند. برای production "
            "یک Redis تنظیم و RATELIMIT_STORAGE_URI=redis://... را ست کنید.",
            RuntimeWarning, stacklevel=2,
        )
    app.config['MAX_CONTENT_LENGTH']    = 50 * 1024 * 1024
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
    app.config['SESSION_REFRESH_EACH_REQUEST'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    # پشت nginx با HTTPS، کوکی‌ها فقط روی اتصال امن ارسال شوند (با ست‌کردن env)
    if os.environ.get('SESSION_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes'):
        app.config['SESSION_COOKIE_SECURE'] = True
    # CSRF توکن در طول session معتبر می‌ماند (پیش‌فرض ۱ ساعت است)
    app.config['WTF_CSRF_TIME_LIMIT'] = None

    # پشت reverse proxy (nginx)، هدرهای X-Forwarded-* را اعتماد کن
    if os.environ.get('BEHIND_PROXY', '').lower() in ('1', 'true', 'yes'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config['UPLOAD_FOLDER']      = os.path.join(
        os.path.dirname(__file__), '..', 'static', 'uploads'
    )

    db_path = os.path.join(os.path.dirname(__file__), '..', 'noyan.db')
    db_url  = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
    # Heroku / Railway deliver postgres:// — SQLAlchemy 2.x needs postgresql://
    if db_url.startswith('postgres://'):
        db_url = 'postgresql://' + db_url[len('postgres://'):]

    is_sqlite = db_url.startswith('sqlite')
    engine_kwargs = {'connect_args': {'check_same_thread': False}} if is_sqlite else {
        'pool_pre_ping': True,
        'pool_size': 5,
        'max_overflow': 10,
    }
    engine = create_engine(db_url, **engine_kwargs)
    Base.metadata.create_all(engine)
    _migrate(engine)

    global db_session
    db_session = scoped_session(sessionmaker(bind=engine))
    app.db = db_session

    @app.teardown_appcontext
    def _close(exc=None): db_session.remove()

    # صفحات HTML (عمومی و پنل) هرگز نباید توسط مرورگر/سرویس‌ورکر کش شوند —
    # وگرنه بعد از ذخیره تنظیمات سایت (لوگو، عنوان، درباره ما و...) کاربر
    # ممکن است همچنان نسخه قدیمی صفحه را ببیند تا رفرش کامل بزند. فایل‌های
    # static و آپلودی از این قانون مستثنا هستند تا سرعت لود صفحه افت نکند.
    @app.after_request
    def _no_cache_html(resp):
        if resp.mimetype == 'text/html' and not request.path.startswith(('/static/', '/uploads/')):
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
        return resp

    # هدرهای امنیتی — دفاع در عمق (در کنار escaping خودکار Jinja٬ اعتبارسنجی
    # آپلود و غیره؛ جایگزین آن‌ها نیست). CSP اجازه اسکریپت/استایل inline را
    # می‌دهد چون قالب‌های موجود از آن زیاد استفاده می‌کنند (بازنویسی کامل به
    # nonce خارج از محدوده این تغییر است)٬ اما بارگذاری منابع را به دامنه خود
    # + CDNهای شناخته‌شده (فونت گوگل٬ jsDelivr برای تقویم شمسی٬ نقشه OSM)
    # محدود می‌کند تا از exfiltration/کلیک‌جکینگ/embed مخرب جلوگیری شود.
    @app.after_request
    def _security_headers(resp):
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
        resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if resp.mimetype == 'text/html':
            resp.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: blob:; "
                "media-src 'self'; "
                "connect-src 'self'; "
                "frame-src https://www.openstreetmap.org; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
            )
        if app.config.get('SESSION_COOKIE_SECURE'):
            resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return resp

    # مسیر مستقیم static برای مدارک حساس بسته می‌شود — فقط از /uploads/
    # (که کنترل دسترسی دارد) قابل دریافت هستند.
    @app.before_request
    def _block_static_sensitive():
        p = request.path
        if (p.startswith('/static/uploads/requests/') or p.startswith('/static/uploads/payments/')
                or p.startswith('/static/uploads/member_docs/') or p.startswith('/static/uploads/marketplace/')):
            from flask import abort
            abort(403)

    # تا وقتی عضو اطلاعات هویتی‌اش را تکمیل نکرده، اجازه استفاده از بقیه پنل
    # (هر صفحه دیگر جز /dashboard/ خودش، و هر API غیر از profile) را ندارد —
    # قبلاً فقط صفحه اصلی پنل این را بررسی می‌کرد و بقیه صفحات/APIها با URL
    # مستقیم قابل دسترس بودند.
    @app.before_request
    def _require_complete_profile():
        if not current_user.is_authenticated or current_user.role != 'member' or current_user.is_profile_complete():
            return
        p = request.path
        if p.startswith('/api/'):
            if not p.startswith('/api/profile'):
                from flask import jsonify
                return jsonify(error='ابتدا اطلاعات هویتی خود را تکمیل کنید.'), 403
            return
        if p.startswith('/dashboard') and p not in ('/dashboard', '/dashboard/'):
            return redirect(url_for('dashboard.home'))

    from .extensions import csrf, limiter
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view    = 'auth.login'
    login_manager.login_message = 'لطفاً وارد شوید.'

    @login_manager.user_loader
    def load_user(uid): return db_session.get(User, int(uid))

    from .routes.auth        import bp as auth_bp
    from .routes.dashboard   import bp as dash_bp
    from .routes.public      import bp as pub_bp
    from .routes.forms_api   import bp as forms_api_bp
    from .routes.forms_dash  import bp as forms_dash_bp
    from .routes.api         import all_blueprints as api_blueprints

    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp,       url_prefix='/dashboard')
    app.register_blueprint(forms_api_bp,  url_prefix='/api')
    app.register_blueprint(forms_dash_bp, url_prefix='/dashboard')
    app.register_blueprint(pub_bp)
    for bp in api_blueprints:
        app.register_blueprint(bp, url_prefix='/api')

    # webhook بله از سرور خارجی می‌آید — CSRF برایش معنا ندارد
    csrf.exempt(app.view_functions['bale.bale_webhook'])
    # صفحه جزئیات آگهی بازار، صفحه‌ای مستقل و بدون توکن CSRF است (برای خریدار
    # مهمانِ بدون حساب کاربری) — این endpoint خودش rate-limited است و فقط
    # یک درخواست خرید کم‌ریسک می‌سازد، نه یک عملیات حساس روی حساب کاربری
    csrf.exempt(app.view_functions['marketplace.submit_purchase_request'])

    # خطاهای داده دیتابیس (مثل طول بیش از حد فیلد) → پاسخ ۴۰۰ فارسی به‌جای ۵۰۰
    from flask import jsonify
    from sqlalchemy.exc import DataError, IntegrityError

    @app.errorhandler(DataError)
    def _data_error(e):
        db_session.rollback()
        # این خطا معمولاً یعنی یک ستون در دیتابیس واقعی کوتاه‌تر از حدی است که
        # کد انتظار دارد (مثلاً migration هنوز اجرا نشده) — بدون لاگ دقیق منشأ
        # آن (کدام جدول/ستون) قابل ردیابی نیست، چون این handler جدا از handler
        # عمومی خطاهای ۵۰۰ است و قبلاً چیزی لاگ نمی‌شد.
        app.logger.error('DataError at %s: %s', request.path, str(getattr(e, 'orig', e))[:500])
        _notify_admins_error(e)
        return jsonify(error='یکی از فیلدها طولانی‌تر از حد مجاز است. مقادیر را بررسی کنید.'), 400

    @app.errorhandler(IntegrityError)
    def _integrity_error(e):
        db_session.rollback()
        return jsonify(error='ثبت اطلاعات با محدودیت دیتابیس تداخل دارد (مقدار تکراری یا وابستگی).'), 400

    from .utils.export import ExportDependencyError

    @app.errorhandler(ExportDependencyError)
    def _export_dependency_error(e):
        # فقط ادمین/مسئول مالی به این route ها دسترسی دارند، پس نمایش پیام
        # دقیق (به‌جای پیام عمومی ۵۰۰) امن و برای عیب‌یابی سریع مفید است
        db_session.rollback()
        app.logger.error('ExportDependencyError at %s: %s', request.path, e)
        _notify_admins_error(e)
        return jsonify(error=str(e)), 500

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def _csrf_error(e):
        # درخواست‌های API پاسخ JSON می‌گیرند تا فرانت بتواند پیام درست نشان دهد
        if request.path.startswith('/api/'):
            return jsonify(error=f'CSRF: {e.description} — صفحه را رفرش کنید.'), 400
        return e

    @app.errorhandler(404)
    def _not_found(e):
        # صفحه ۴۰۴ برندشده فقط برای مسیرهای عمومی سایت — پنل و API همان
        # رفتار پیش‌فرض/JSON خودشان را دارند
        if request.path.startswith('/api/'):
            return jsonify(error='یافت نشد.'), 404
        if request.path.startswith('/dashboard'):
            return e
        try:
            row = db_session.get(SiteSetting, 'site_title')
            site_title = row.value if row else 'سامانه مدیریت اعضا و امور مالی'
        except Exception:
            site_title = 'سامانه مدیریت اعضا و امور مالی'
        return render_template('public/404.html', site_title=site_title), 404

    # ── لاگ‌گیری خطاها روی فایل + اطلاع خطای ۵۰۰ به ادمین‌های بله ──────────────
    if not app.config.get('TESTING'):
        _setup_error_logging(app)

        from werkzeug.exceptions import HTTPException

        @app.errorhandler(Exception)
        def _handle_uncaught(e):
            # خطاهای HTTP معمول (۴۰۴، ۴۰۳، ...) دست‌نخورده عبور می‌کنند
            if isinstance(e, HTTPException):
                return e
            db_session.rollback()
            app.logger.exception('Unhandled error at %s', request.path)
            _notify_admins_error(e)
            if request.path.startswith('/api/'):
                return jsonify(error='خطای داخلی سرور. موضوع ثبت شد و بررسی می‌شود.'), 500
            return ('<div style="font-family:Vazirmatn,Tahoma,sans-serif;direction:rtl;'
                    'text-align:center;padding:60px 20px"><h1>خطای داخلی سرور</h1>'
                    '<p>موضوع ثبت شد و بررسی می‌شود. لطفاً بعداً تلاش کنید.</p>'
                    '<a href="/">بازگشت به صفحه اصلی</a></div>'), 500

    # نسخه سامانه در همه template ها در دسترس است: {{ app_version }}
    from .version import __version__

    @app.context_processor
    def _inject_version():
        return {'app_version': __version__}

    # لوگوی سایت در همه template ها در دسترس است (برای favicon/هدر)
    # اگر route از قبل site_settings را صریحاً پاس داده باشد، همان مقدار اولویت دارد
    @app.context_processor
    def _inject_site_logo():
        try:
            row = db_session.get(SiteSetting, 'site_logo')
            return {'site_logo': row.value if row else None}
        except Exception:
            return {'site_logo': None}

    _seed(db_session)
    return app


def _migrate(engine):
    """Add new columns to existing databases without breaking (SQLite + PostgreSQL)."""
    from sqlalchemy import text
    dialect = engine.dialect.name  # 'sqlite' or 'postgresql'

    with engine.connect() as conn:
        def _add(table, col, col_type):
            try:
                if dialect == 'postgresql':
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"
                    ))
                else:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    ))
                conn.commit()
            except Exception:
                conn.rollback()

        _add('projects',          'map_lat',         'VARCHAR(20)')
        _add('projects',          'map_lon',          'VARCHAR(20)')
        _add('announcements',     'image_path',       'VARCHAR(260)')
        _add('transfer_requests', 'extra_photo_path', "VARCHAR(260) DEFAULT ''")
        _add('users',    'gender',           'VARCHAR(10)')
        _add('users',    'id_number',        'VARCHAR(20)')
        _add('users',    'birth_place',      'VARCHAR(60)')
        _add('users',    'marital_status',   'VARCHAR(20)')
        _add('users',    'landline',         'VARCHAR(15)')
        _add('users',    'address',          'TEXT')
        _add('users',    'postal_code',      'VARCHAR(10)')
        _add('users',    'occupation',       'VARCHAR(80)')
        _add('users',    'email',            'VARCHAR(120)')
        _add('users',    'bank_name',        'VARCHAR(60)')
        _add('users',    'account_number',   'VARCHAR(30)')
        _add('users',    'iban',             'VARCHAR(30)')
        _add('users',    'bale_chat_id',     'VARCHAR(40)')
        _add('users',    'bale_link_code',   'VARCHAR(10)')
        _add('users',    'bale_link_code_expires_at', 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME')
        _add('users',    'father_name',      'VARCHAR(80)')
        _add('users',    'birth_date',       'VARCHAR(20)')
        _add('users',    'emergency_phone',  'VARCHAR(15)')
        _add('users',    'profile_complete', 'BOOLEAN DEFAULT TRUE')
        _add('users',    'personnel_code',   'VARCHAR(20)')
        _add('users',    'deposit_id',       'VARCHAR(30)')
        _add('users',    'org_unit',         'VARCHAR(80)')
        _add('deposit_vouchers', 'source',             "VARCHAR(20) DEFAULT 'manual'")
        _add('deposit_vouchers', 'branch_code',        "VARCHAR(20) DEFAULT ''")
        _add('deposit_vouchers', 'branch_name',        "VARCHAR(80) DEFAULT ''")
        _add('deposit_vouchers', 'channel',            "VARCHAR(20) DEFAULT ''")
        _add('deposit_vouchers', 'bank_balance_after', 'BIGINT')
        _add('deposit_vouchers', 'category',           "VARCHAR(20) DEFAULT 'member_deposit'")
        _add('booklets', 'serial',           'INTEGER')
        _add('booklets', 'booklet_number',   "VARCHAR(30) DEFAULT ''")
        _add('booklets', 'contract_no',      "VARCHAR(80) DEFAULT ''")
        _add('booklets', 'contract_date',    "VARCHAR(20) DEFAULT ''")
        _add('booklets', 'contract_amount',  'BIGINT DEFAULT 0')
        _add('booklets', 'notes',            'TEXT')
        _add('booklets', 'receipt_path',     'VARCHAR(260)')
        _add('booklets', 'deleted_at',       'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME')
        _add('activity_logs', 'id',          'INTEGER PRIMARY KEY')
        _add('activity_logs', 'user_id',     'INTEGER')
        _add('activity_logs', 'action',      "VARCHAR(80) DEFAULT ''")
        _add('activity_logs', 'category',    "VARCHAR(40) DEFAULT 'general'")
        _add('activity_logs', 'detail',      'TEXT')
        _add('activity_logs', 'ip',          'VARCHAR(45)')
        ts = 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME'
        _add('activity_logs', 'created_at',  ts)
        _add('tickets',         'closed_at',          ts)
        _add('tickets',         'listing_id',         'INTEGER REFERENCES marketplace_listings(id)')
        _add('ticket_messages', 'is_admin',            'BOOLEAN DEFAULT FALSE')
        _add('transfer_requests', 'note',              'TEXT')
        _add('transfer_requests', 'review_note',       'TEXT')
        _add('transfer_requests', 'reviewed_at',       ts)
        _add('transfer_requests', 'receipt_path',      'VARCHAR(260)')
        _add('transfer_requests', 'agreement_path',    'VARCHAR(260)')
        _add('transfer_requests', 'sana_form_path',    'VARCHAR(260)')
        _add('transfer_requests', 'id_first_page_path','VARCHAR(260)')
        _add('transfer_requests', 'national_front_path','VARCHAR(260)')
        _add('transfer_requests', 'national_back_path', "VARCHAR(260) DEFAULT ''")
        _add('slides',          'media_type',          "VARCHAR(10) DEFAULT 'image'")
        _add('slides',          'video_path',          'VARCHAR(260)')
        _add('slides',          'image_path',          'VARCHAR(260)')
        _add('slides',          'bg_color',            "VARCHAR(20) DEFAULT '#1A2035'")
        _add('slides',          'subtitle',            'VARCHAR(200)')
        _add('slides',          'active',              'BOOLEAN DEFAULT TRUE')
        _add('slides',          'order',               'INTEGER DEFAULT 0')
        _add('projects',        'active',              'BOOLEAN DEFAULT TRUE')
        _add('projects',        'order',               'INTEGER DEFAULT 0')
        _add('projects',        'image_path',          'VARCHAR(260)')
        _add('payments',        'receipt_path',        'VARCHAR(260)')
        _add('payments',        'booklet_id',          'INTEGER REFERENCES booklets(id)')
        _add('notifications',   'type',                "VARCHAR(20) DEFAULT 'info'")
        _add('notifications',   'read',                'BOOLEAN DEFAULT FALSE')
        # project_gallery and announcement_media tables created via Base.metadata.create_all
        _add('announcements', 'project_id', 'INTEGER REFERENCES projects(id)')
        _add('announcements', 'pub_date',   ts)
        _add('announcements', 'expires_at', ts)
        # form builder — tables created via Base.metadata.create_all; add missing cols for existing DBs
        _add('forms', 'allow_edit',      'BOOLEAN DEFAULT 0')
        _add('forms', 'max_submissions', 'INTEGER DEFAULT 0')
        _add('forms', 'expires_at',      ts)
        _add('forms', 'success_msg',     'TEXT')
        _add('forms', 'slug',            'VARCHAR(100)')
        _add('forms', 'status',          "VARCHAR(20) DEFAULT 'draft'")
        _add('forms', 'is_public',       'BOOLEAN DEFAULT TRUE')
        _add('forms', 'multi_step',      'BOOLEAN DEFAULT FALSE')
        _add('forms', 'created_by',      'INTEGER')
        _add('forms', 'created_at',      ts)
        _add('forms', 'updated_at',      ts)
        _add('forms', 'restrict_access', 'BOOLEAN DEFAULT FALSE')
        # form_allowed_people table created via Base.metadata.create_all
        # member_ledger_entries table created via Base.metadata.create_all

        # پهن‌سازی ستون‌های مبلغ از INTEGER به BIGINT — رفع محدودیت ۹ رقمی برای اعداد بزرگ
        def _widen_bigint(table, col):
            try:
                if dialect == 'postgresql':
                    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE BIGINT"))
                    conn.commit()
                # SQLite: ستون‌های INTEGER از قبل ظرفیت نامحدود عملی دارند (dynamic typing)، نیازی به ALTER نیست
            except Exception:
                conn.rollback()

        _widen_bigint('booklets',           'contract_amount')
        _widen_bigint('payment_plans',      'total_amount')
        _widen_bigint('payments',           'amount')
        _widen_bigint('deposit_vouchers',   'amount')
        _widen_bigint('voucher_allocations','amount')
        _widen_bigint('expense_vouchers',   'amount')

        # آزادسازی کد دفترچه‌هایی که قبل از این تغییر soft-delete شده بودند —
        # همان تغییری که هنگام حذف جدید انجام می‌شود (پیشوند DEL{id}-)، یک‌بار
        # برای رکوردهای قدیمی هم به‌صورت گذشته‌نگر اعمال می‌شود تا کدشان برای
        # دفترچه‌های جدید آزاد شود.
        try:
            rows = conn.execute(text(
                "SELECT id, code FROM booklets WHERE deleted_at IS NOT NULL AND code NOT LIKE 'DEL%'"
            )).fetchall()
            for bid, code in rows:
                new_code = f"DEL{bid}-{code}"[:30]
                conn.execute(text("UPDATE booklets SET code = :nc WHERE id = :bid"),
                             {"nc": new_code, "bid": bid})
            conn.commit()
        except Exception:
            conn.rollback()

        # کد دفترچه (که معمولاً همان شماره قرارداد است) قبلاً باید بین همه
        # پروژه‌ها یکتا می‌بود؛ درصورتی‌که دو پروژه مختلف هر دو شماره قرارداد
        # مشابه داشته باشند (مثلاً هر دو «۳»)، این محدودیت اشتباه بود. اکنون
        # یکتایی فقط در سطح هر پروژه اعمال می‌شود (project_id + code).
        if dialect == 'postgresql':
            try:
                old_constraint = conn.execute(text(
                    "SELECT tc.constraint_name FROM information_schema.table_constraints tc "
                    "JOIN information_schema.constraint_column_usage ccu "
                    "  ON tc.constraint_name = ccu.constraint_name "
                    "WHERE tc.table_name = 'booklets' AND tc.constraint_type = 'UNIQUE' "
                    "  AND ccu.column_name = 'code' AND tc.constraint_name != 'uq_booklets_project_code'"
                )).fetchall()
                for (cname,) in old_constraint:
                    conn.execute(text(f'ALTER TABLE booklets DROP CONSTRAINT IF EXISTS "{cname}"'))
                conn.execute(text(
                    "ALTER TABLE booklets ADD CONSTRAINT uq_booklets_project_code "
                    "UNIQUE (project_id, code)"
                ))
                conn.commit()
            except Exception:
                conn.rollback()

        # پهن‌سازی ستون‌های آگهی بازار که در عمل خیلی کوچک بودند — کاربران با
        # مقادیر معمولی (مثلاً شماره تماس با پیش‌شماره/فاصله، یا توضیح نوع سهم)
        # با خطای DataError مواجه می‌شدند چون Postgres برخلاف SQLite طول
        # varchar را واقعاً اعمال می‌کند.
        def _widen_varchar(table, col, new_len):
            try:
                if dialect == 'postgresql':
                    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE VARCHAR({new_len})"))
                    conn.commit()
            except Exception:
                conn.rollback()

        _widen_varchar('marketplace_listings', 'contact_phone', 30)
        _widen_varchar('marketplace_listings', 'unit_type', 150)
        # کد موقت آگهی پیش از flush به‌شکل "tmp-<uuid4 hex>" است (۳۶ کاراکتر)
        # که از ظرفیت قبلی ستون code (۳۰ کاراکتر) در PostgreSQL رد می‌شد و
        # ثبت هر آگهی را با DataError شکست می‌داد (روی SQLite قابل بازتولید
        # نبود چون طول varchar در آن اعمال نمی‌شود)
        _widen_varchar('marketplace_listings', 'code', 45)


def _seed(sess):
    from werkzeug.security import generate_password_hash
    from sqlalchemy.exc import IntegrityError
    if not sess.query(User).filter_by(username='admin').first():
        sess.add(User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            first_name='مدیر',
            last_name='سامانه',
            active=True,
            profile_complete=True,
        ))
        # جدا commit می‌شود تا اگر worker دیگری زودتر ساخت، فقط همین بخش rollback شود
        try:
            sess.commit()
        except IntegrityError:
            sess.rollback()
    defaults = [
        ('site_title',    os.environ.get('SITE_TITLE',    'سامانه مدیریت اعضا و امور مالی')),
        ('site_subtitle', os.environ.get('SITE_SUBTITLE', 'سامانه آنلاین مدیریت اعضا و واریزی‌ها')),
        ('site_phone',    os.environ.get('SITE_PHONE',    '')),
        ('site_address',  os.environ.get('SITE_ADDRESS',  '')),
        ('hero_btn_label','ورود اعضا'),
        ('exec_manager',  os.environ.get('EXEC_MANAGER',  '')),
        ('board_rep',     os.environ.get('BOARD_REP',     '')),
        ('board_title',   os.environ.get('BOARD_TITLE',   'هیئت مدیره')),
        ('bale_bot_username', ''),
        ('bale_bot_token',    ''),
        ('sms_api_key',       ''),
        ('sms_template_id',   ''),
        ('sms_line_number',   ''),
        ('transfer_docs_address', ''),
        # بازار خرید و فروش دفترچه‌ها — همه Dynamic، هیچ‌کدام Hard Code نمی‌شوند
        ('marketplace_enabled',        '1'),
        ('marketplace_fee_enabled',    '1'),
        ('marketplace_fee_amount',     '260000'),   # تومان
        ('marketplace_listing_days',   '30'),
        ('marketplace_payment_info',   ''),          # متن اطلاعات حساب/کارت
        ('marketplace_allow_guest_requests', '1'),
        ('marketplace_max_receipt_mb', '5'),
    ]
    OLD_TITLE = 'هیئت امنای مسکن دادگستری زنجان'
    for k, v in defaults:
        row = sess.query(SiteSetting).filter_by(key=k).first()
        if not row:
            sess.add(SiteSetting(key=k, value=v))
        elif k == 'site_title' and row.value == OLD_TITLE:
            row.value = v  # migrate old default title
    try:
        sess.commit()
    except IntegrityError:
        # race میان چند worker هنگام استارت هم‌زمان — رکورد را دیگری ساخته
        sess.rollback()
