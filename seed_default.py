#!/usr/bin/env python3
"""
seed_default.py — ادمین و تنظیمات پایه را می‌سازد.
اطلاعات ادمین از متغیرهای محیطی خوانده می‌شود:

  ADMIN_USERNAME   (پیش‌فرض: admin)
  ADMIN_PASSWORD   (پیش‌فرض: admin123)
  ADMIN_FIRST_NAME (پیش‌فرض: مدیر)
  ADMIN_LAST_NAME  (پیش‌فرض: سامانه)
  SITE_TITLE / SITE_SUBTITLE / SITE_PHONE / SITE_ADDRESS
  EXEC_MANAGER / BOARD_REP / BOARD_TITLE

اجرا:
  python seed_default.py
  یا از طریق: bash seed_default.sh
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# بارگذاری .env اگر python-dotenv نصب است
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'), override=False)
except ImportError:
    pass

from app import create_app
from werkzeug.security import generate_password_hash

# ─── خواندن متغیرها ────────────────────────────────────────────────────────────
ADMIN_USERNAME   = os.environ.get('ADMIN_USERNAME',   'admin')
ADMIN_PASSWORD   = os.environ.get('ADMIN_PASSWORD',   'admin123')
ADMIN_FIRST_NAME = os.environ.get('ADMIN_FIRST_NAME', 'مدیر')
ADMIN_LAST_NAME  = os.environ.get('ADMIN_LAST_NAME',  'سامانه')

SITE_TITLE    = os.environ.get('SITE_TITLE',    'هیئت امنای مسکن دادگستری زنجان')
SITE_SUBTITLE = os.environ.get('SITE_SUBTITLE', 'سامانه آنلاین مدیریت دفترچه مالکیت')
SITE_PHONE    = os.environ.get('SITE_PHONE',    '')
SITE_ADDRESS  = os.environ.get('SITE_ADDRESS',  '')
EXEC_MANAGER  = os.environ.get('EXEC_MANAGER',  'علی غفاری')
BOARD_REP     = os.environ.get('BOARD_REP',     'خلیل باقری')
BOARD_TITLE   = os.environ.get('BOARD_TITLE',   'هیئت رئیسه امنای مسکن دادگستری استان زنجان')

# ─── اجرا ──────────────────────────────────────────────────────────────────────
app = create_app()

with app.app_context():
    from app import db_session
    from app.models import User, SiteSetting, Slide

    # ── ادمین ──────────────────────────────────────────────────────────────────
    admin = db_session.query(User).filter_by(username=ADMIN_USERNAME).first()
    if admin:
        admin.password_hash   = generate_password_hash(ADMIN_PASSWORD)
        admin.first_name      = ADMIN_FIRST_NAME
        admin.last_name       = ADMIN_LAST_NAME
        admin.role            = 'admin'
        admin.active          = True
        admin.profile_complete = True
        print(f'  ↻  ادمین «{ADMIN_USERNAME}» به‌روزرسانی شد')
    else:
        db_session.add(User(
            username=ADMIN_USERNAME,
            password_hash=generate_password_hash(ADMIN_PASSWORD),
            role='admin',
            first_name=ADMIN_FIRST_NAME,
            last_name=ADMIN_LAST_NAME,
            active=True,
            profile_complete=True,
        ))
        print(f'  ✓  ادمین «{ADMIN_USERNAME}» ساخته شد')

    # ── تنظیمات سایت ──────────────────────────────────────────────────────────
    site_settings = {
        'site_title':    SITE_TITLE,
        'site_subtitle': SITE_SUBTITLE,
        'site_phone':    SITE_PHONE,
        'site_address':  SITE_ADDRESS,
        'hero_btn_label':'ورود اعضا',
        'exec_manager':  EXEC_MANAGER,
        'board_rep':     BOARD_REP,
        'board_title':   BOARD_TITLE,
    }
    for k, v in site_settings.items():
        row = db_session.query(SiteSetting).filter_by(key=k).first()
        if row:
            row.value = v
        else:
            db_session.add(SiteSetting(key=k, value=v))
    print(f'  ✓  {len(site_settings)} تنظیم سایت ذخیره شد')

    # ── اسلاید پیش‌فرض (فقط اگر هیچ اسلایدی نبود) ────────────────────────────
    if db_session.query(Slide).count() == 0:
        db_session.add(Slide(
            title=SITE_TITLE,
            subtitle=SITE_SUBTITLE,
            bg_color='#1A2640',
            order=1,
            active=True,
        ))
        print('  ✓  اسلاید پیش‌فرض ساخته شد')

    db_session.commit()

print('')
print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
print(f'  ✅ آماده!  ورود ادمین:  {ADMIN_USERNAME} / {ADMIN_PASSWORD}')
print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
