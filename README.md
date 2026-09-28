# سامانه مدیریت اعضا و امور مالی

سامانه جامع مدیریت اعضا، پروژه‌ها، دفترچه‌های مالکیت، نقل و انتقال، حسابداری تعاونی، فرم‌ساز، پشتیبانی و اطلاع‌رسانی (پیامک + ربات بله).

نسخه‌ی سفارشی‌شده — تفاوت‌های اصلی نسبت به نسخه پایه (`coop`):
- اطلاعات عضو شامل فیلدهای اختصاصی **کدپرسنلی**، **شناسه واریز** و **واحد سازمانی**.
- امکان **وارد کردن مستقیم صورت‌حساب خام بانکی (اکسل)** از پنل حسابداری و تطبیق خودکار هر واریزی با عضو صاحب «شناسه واریز» — بدون نیاز به ثبت دستی تک‌تک تراکنش‌ها.
- گزارش «واریزی‌های بدون تطبیق» برای رسیدگی به تراکنش‌هایی که شناسه واریز آن‌ها یافت نشد.
- گزارش تفکیک واریزی‌ها بر اساس «واحد سازمانی».

نسخه فعلی: **[app/version.py](app/version.py)** — تاریخچه کامل در **[CHANGELOG.md](CHANGELOG.md)**.

---

## فهرست مطالب

- [زبان‌ها و تکنولوژی‌ها](#زبانها-و-تکنولوژیها)
- [معماری](#معماری)
- [ویژگی‌ها](#ویژگیها)
- [نقش‌های کاربری](#نقشهای-کاربری)
- [پیش‌نیازها](#پیشنیازها)
- [نصب و راه‌اندازی محلی](#نصب-و-راهاندازی-محلی)
- [متغیرهای محیطی](#متغیرهای-محیطی)
- [ساختار پروژه](#ساختار-پروژه)
- [مدل داده](#مدل-داده)
- [مسیرهای API](#مسیرهای-api)
- [امنیت](#امنیت)
- [پیامک (sms.ir) و ربات بله](#پیامک-smsir-و-ربات-بله)
- [استقرار روی سرور (Production)](#استقرار-روی-سرور-production)
- [بکاپ و کارهای زمان‌بندی‌شده](#بکاپ-و-کارهای-زمانبندیشده)
- [تست‌ها](#تستها)
- [استانداردهای توسعه](#استانداردهای-توسعه)

---

## زبان‌ها و تکنولوژی‌ها

| لایه | زبان / فناوری |
|---|---|
| Backend | **Python 3.11** (Flask 3) |
| دیتابیس | SQLAlchemy 2 ORM → **PostgreSQL** (تولید) / **SQLite** (توسعه و تست) |
| Frontend | **HTML + CSS خالص + Vanilla JavaScript** (بدون فریم‌ورک SPA) — رندر سمت سرور با Jinja2 |
| قالب‌ها | Jinja2 (RTL فارسی، فونت Vazirmatn) |
| Auth | Flask-Login (session-based) + Flask-WTF (CSRF) + Flask-Limiter (rate limit) |
| سرور Production | Gunicorn پشت Nginx، مدیریت‌شده با systemd |
| پیامک | sms.ir (REST API) |
| پیام‌رسان | ربات بله (Bale Messenger Bot API) |
| اکسل | openpyxl (import/export) |
| تصویر | Pillow (سمت سرور) + Canvas API (فشرده‌سازی سمت کلاینت) |
| تست | pytest |

خلاصه یک‌خطی: **یک اپ Flask (پایتون) با رندر سمت سرور (Jinja2 + Vanilla JS)**، بدون فریم‌ورک فرانت‌اند جاوااسکریپتی (React/Vue/... ندارد) و بدون TypeScript.

---

## معماری

معماری **Modular Layered** — هر دامنه کسب‌وکار (اعضا، پروژه‌ها، مالی، حسابداری، ...) یک ماژول مستقل در لایه API دارد؛ لایه‌ها به‌وضوح از هم جدا هستند:

```
Presentation      →  templates/**                (Jinja2, RTL, Vanilla JS)
HTTP Layer        →  app/routes/api/*.py          (۱۴ Flask Blueprint مستقل)
                     app/routes/auth.py, dashboard.py, public.py,
                     forms_api.py, forms_dash.py
Shared / Utils    →  app/utils/*.py               (files, http, jalali, validation)
Domain Models     →  app/models.py                (۳۰ مدل SQLAlchemy)
Constants         →  app/constants.py             (Role, Status enums, ...)
Infra / Bootstrap →  app/__init__.py              (app factory، migration خودکار، seed، لاگ خطا)
Integrations      →  app/bot.py (بله)، app/sms.py (sms.ir)، app/otp.py (کد بازیابی)
```

### لایه API (`app/routes/api/`)

هر فایل یک Blueprint مستقل با پیشوند مشترک `/api` است:

| ماژول | مسئولیت |
|---|---|
| `projects.py` | پروژه‌ها، گالری، اعضای هیئت پروژه |
| `members.py` | CRUD اعضا، import/export اکسل، ویرایش و تغییر رمز توسط مدیر |
| `booklets.py` | دفترچه‌های مالکیت (soft-delete) |
| `finance.py` | طرح‌های اقساط، پرداخت‌ها |
| `transfers.py` | درخواست نقل و انتقال (۲ مرحله‌ای)، جستجو/فیلتر، تاریخچه |
| `accounting.py` | حسابداری تعاونی: حساب‌ها، اسناد واریز/هزینه، تخصیص، کارت حساب عضو |
| `overview.py` | داشبورد نمای کلی مدیر |
| `announcements.py` | اطلاعیه‌ها + رسانه |
| `notifications.py` | اعلان‌های درون‌سامانه‌ای |
| `tickets.py` | سیستم تیکت پشتیبانی |
| `settings.py` | تنظیمات سایت، اسلایدها، آپلود عکس رهبران |
| `bale.py` | اتصال/وضعیت/broadcast ربات بله + تنظیم خودکار webhook |
| `activity.py` | لاگ فعالیت با فیلتر |
| `reports.py` | گزارش‌گیری |
| `profile.py` | پروفایل شخصی کاربر |

### چرا این معماری

- **جداسازی مسئولیت**: هر بلوپرینت فقط دامنهٔ خودش را می‌داند؛ افزودن ماژول جدید یعنی یک فایل جدید + ثبت در `app/routes/api/__init__.py`
- **لایه Utils مشترک**: اعتبارسنجی، آپلود فایل امن، مقایسه تاریخ شمسی و کمک‌توابع HTTP یک‌بار نوشته و همه‌جا استفاده می‌شوند
- **بدون ORM مخفی در View**: تمام دسترسی دیتابیس در لایه API است، نه در template
- **Migration خودکار سبک‌وزن**: به‌جای Alembic، تابع `_migrate()` با `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` هنگام استارت اجرا می‌شود — ساده و بدون وابستگی اضافه، مناسب اندازه فعلی پروژه

---

## ویژگی‌ها

### پنل مدیریت (Admin)
- مدیریت اعضا: ایجاد/ویرایش/حذف (cascade)، فعال/غیرفعال، **تغییر رمز توسط مدیر**، صفحه‌بندی و جستجوی سمت سرور
- واردسازی انبوه اعضا از اکسل با تمپلیت آماده
- آرشیو اسناد هر عضو (قرارداد، مدارک هویتی، مالی) با کنترل دسترسی
- مدیریت پروژه‌ها با گالری تصویر/ویدیو و موقعیت جغرافیایی
- دفترچه‌های مالکیت با soft-delete (حفظ سوابق مالی)
- **نقل و انتقال دومرحله‌ای**: تأیید اولیه → دریافت حضوری مدارک → تأیید نهایی، با جستجو/فیلتر و آدرس تحویل مدارک قابل تنظیم
- **حسابداری تعاونی کامل**:
  - تعریف حساب‌های دریافت وجوه (مدیر، هیئت امنا، ...)
  - سند واریز با شماره سریال، واریزکننده (عضو یا آزاد)، تاریخ/ساعت، روش، فیش
  - **تخصیص سند به اقساط** (Reconciliation) — تسویه خودکار وضعیت قسط
  - سند هزینه (خروجی وجه) با دسته‌بندی؛ موجودی حساب = واریزی − هزینه
  - کارت حساب عضو (کاردکس) قابل چاپ + خروجی Excel
  - رسید چاپی سند واریز
  - داشبورد مالی و تفکیک مالی به‌ازای پروژه
  - نقش «مسئول مالی» با دسترسی محدود به بخش مالی
- **داشبورد نمای کلی مدیر**: اعضای فعال، وصولی ماه، اقساط معوق، کارهای در انتظار
- فرم‌ساز پویا (Form Builder) با فیلدهای چندگانه، مراحل، اعتبارسنجی و گزارش پاسخ‌ها
- سیستم تیکتینگ پشتیبانی با دسته‌بندی و اولویت
- مدیریت اسلایدر صفحه اصلی (افزودن/ویرایش/حذف/نمایش-پنهان)
- لاگ فعالیت کاربران با IP، فیلتر و جستجو
- ارسال پیام گروهی از طریق پیامک و ربات بله

### پنل اعضا (Member)
- مشاهده دفترچه‌های مالکیت و قرارداد
- ثبت درخواست نقل و انتقال با آپلود مدارک (فشرده‌سازی خودکار تصویر سمت کلاینت)
- کارت حساب شخصی (بدهی، پرداختی، مانده) قابل چاپ
- مشاهده اطلاعیه‌ها، اعلان‌ها و ارسال تیکت پشتیبانی
- اتصال به ربات بله برای دریافت اطلاع‌رسانی

### سایت عمومی
- اسلایدر (تصویر/ویدیو)، معرفی پروژه‌ها با گالری، اطلاعیه‌ها، فرم‌های عمومی
- واکنش‌گرا و PWA (نصب روی موبایل)

---

## نقش‌های کاربری

| نقش | دسترسی |
|---|---|
| `admin` | دسترسی کامل به همه بخش‌ها |
| `finance` | فقط بخش مالی و حسابداری (بدون مدیریت اعضا/تنظیمات) |
| `member` | داشبورد شخصی، دفترچه‌ها، پرداخت‌ها، درخواست‌ها، تیکت |

---

## امنیت

- رمز عبور: هش با Werkzeug (scrypt)
- **CSRF Protection** (Flask-WTF) روی همه فرم‌ها و درخواست‌های API
- **Rate Limiting** (Flask-Limiter) روی ورود، فراموشی رمز و تأیید OTP
- **کپچای ریاضی** بعد از ۳ ورود ناموفق (بدون سرویس خارجی)
- بازیابی رمز با کد یکبارمصرف (OTP) ذخیره‌شده در دیتابیس (نه حافظه — امن برای اجرای چند-worker)، ارسال از طریق پیامک با fallback به ربات بله
- کنترل دسترسی فایل: پوشه‌های حساس (مدارک نقل و انتقال، فیش پرداخت، اسناد اعضا) فقط برای مالک فایل یا نقش مالی/مدیر
- کوکی‌های session: `HttpOnly` + `SameSite=Lax` + `Secure` (پشت HTTPS)
- اعتبارسنجی متمرکز ورودی‌ها (طول فیلد، فرمت کد ملی/کد پستی، نرمال‌سازی ارقام فارسی)
- لاگ خطای چرخشی (`logs/app.log`) + اطلاع خودکار خطای ۵۰۰ به ادمین‌های متصل به بله، بدون افشای جزئیات فنی به کاربر

---

## پیش‌نیازها

- Python 3.11 (یا 3.9+)
- pip
- (تولید) PostgreSQL 13+، Nginx، Gunicorn
- (اختیاری) کلید API پنل پیامکی sms.ir برای بازیابی رمز و یادآوری اقساط
- (اختیاری) توکن ربات بله برای اطلاع‌رسانی

---

## نصب و راه‌اندازی محلی

```bash
git clone <repo-url>
cd coop

python3 -m venv env
source env/bin/activate        # ویندوز: env\Scripts\activate

pip install -r requirements.txt

cp .env.example .env           # مقادیر را ویرایش کنید

python run.py                  # http://localhost:5000
```

### ورود پیش‌فرض

| نام کاربری | رمز عبور | نقش |
|---|---|---|
| `admin` | `admin123` | مدیر |

⚠️ در production بلافاصله این رمز را عوض کنید (از پنل، دکمهٔ ویرایش عضو).

---

## متغیرهای محیطی

الگوی کامل در **[.env.example](.env.example)**. مهم‌ترین‌ها:

| متغیر | توضیح |
|---|---|
| `SECRET_KEY` | کلید رمزنگاری session — در production ثابت و تصادفی |
| `DATABASE_URL` | `postgresql://...` (تولید) یا `sqlite:///noyan.db` (توسعه) |
| `BALE_TOKEN` | توکن ربات بله (یا از پنل ادمین) |
| `SMSIR_API_KEY` / `SMSIR_TEMPLATE_ID` / `SMSIR_LINE_NUMBER` | پنل پیامکی sms.ir (یا از پنل ادمین) |
| `FLASK_DEBUG` | فقط توسعه محلی — در production هرگز ست نشود |
| `BEHIND_PROXY` | پشت Nginx روی `1` بگذارید (ProxyFix) |
| `SESSION_COOKIE_SECURE` | فقط وقتی HTTPS فعال است روی `1` |
| `RATELIMIT_STORAGE_URI` | برای چند-worker/Redis در مقیاس بالا |

---

## ساختار پروژه

```
coop/
├── app/
│   ├── __init__.py          # app factory، migration خودکار، seed، لاگ خطا، error handlers
│   ├── models.py            # ۳۰ مدل SQLAlchemy
│   ├── constants.py         # Role، Status enum ها، مقادیر پیش‌فرض
│   ├── extensions.py        # نمونه‌های CSRFProtect و Limiter
│   ├── version.py           # نسخه سامانه ({{ app_version }} در templates)
│   ├── bot.py                # ربات بله: send، broadcast، webhook، notify
│   ├── sms.py                 # پنل پیامکی sms.ir: verify code، پیام عادی، اعتبار
│   ├── otp.py                 # کدهای بازیابی رمز روی دیتابیس
│   ├── utils/
│   │   ├── files.py          # آپلود امن (اعتبارسنجی نوع/حجم)
│   │   ├── http.py           # require_admin/require_finance، log_activity
│   │   ├── jalali.py         # تبدیل و مقایسه تاریخ شمسی
│   │   └── validation.py     # اعتبارسنجی فیلدهای کاربر
│   └── routes/
│       ├── auth.py           # ورود، فراموشی رمز (OTP پیامک/بله)، خروج
│       ├── dashboard.py      # صفحات پنل (HTML)
│       ├── public.py         # سایت عمومی + سرو امن فایل آپلودی
│       ├── forms_api.py      # API فرم‌ساز
│       ├── forms_dash.py     # صفحات فرم‌ساز
│       └── api/              # ۱۴ Blueprint دامنه‌محور (بالا توضیح داده شد)
│
├── templates/
│   ├── base.html
│   ├── auth/                 # login، forgot-password، verify-otp، reset-password
│   ├── dashboard/             # ۲۷ صفحه پنل (اعضا، پروژه‌ها، حسابداری، فرم‌ساز، ...)
│   └── public/index.html
│
├── static/
│   ├── css/ (main.css، public.css)
│   ├── js/ (app.js، csrf.js، scene.js)
│   └── uploads/               # فایل‌های آپلودی (gitignore)
│
├── tests/                     # pytest — ۳۷۵+ تست
├── scripts/
│   ├── backup_db.sh           # بکاپ خودکار دیتابیس (Postgres/SQLite)
│   └── mark_overdue.py        # علامت‌گذاری اقساط معوق + یادآوری
├── deploy/
│   ├── tmdz.service           # واحد systemd
│   └── nginx.conf             # نمونه پیکربندی nginx
│
├── run.py                     # نقطه ورود توسعه: python run.py
├── gunicorn_conf.py            # پیکربندی production
├── DEPLOY.md                   # راهنمای کامل استقرار
├── CHANGELOG.md                 # تاریخچه نسخه‌ها
├── requirements.txt
└── .env.example
```

---

## مدل داده

### جداول اصلی (۳۰ مدل)

| گروه | جداول |
|---|---|
| کاربران و دسترسی | `users`، `password_reset_codes` |
| پروژه و دفترچه | `projects`، `project_gallery`، `project_members`، `booklets` |
| نقل و انتقال | `transfer_requests`، `transfer_history` |
| حسابداری تعاونی | `coop_accounts`، `deposit_vouchers`، `voucher_allocations`، `expense_vouchers` |
| مالی اقساط | `payment_plans`، `payments` |
| محتوا | `announcements`، `announcement_media`، `slides`، `site_settings` |
| اسناد اعضا | `member_documents` |
| ارتباطات | `notifications`، `tickets`، `ticket_messages`، `activity_logs` |
| فرم‌ساز | `forms`، `form_steps`، `form_fields`، `form_submissions`, `form_submission_values`, `form_submission_history` |

جزئیات کامل ستون‌ها در `app/models.py`.

---

## مسیرهای API

همه مسیرها با پیشوند `/api/` و اکثراً نیازمند احراز هویت. نمونه‌ها (کامل در کد هر ماژول):

| حوزه | نمونه مسیر |
|---|---|
| اعضا | `GET/POST /api/members`، `POST /api/members/<id>`، `POST /api/members/<id>/password` |
| نقل و انتقال | `GET /api/requests?search=&status=&project_id=`، `POST /api/requests/<id>/approve` → `complete` |
| حسابداری | `POST /api/accounting/vouchers`، `POST /api/accounting/vouchers/<id>/allocate`، `GET /api/accounting/member/<id>/statement` |
| داشبورد | `GET /api/overview` |
| پیامک | `POST /api/admin/sms/test`، `GET /api/admin/sms/credit` |
| ربات بله | `POST /api/bale/set-webhook`، `GET /api/bale/webhook-info` |

---

## پیامک (sms.ir) و ربات بله

- **sms.ir**: از پنل ادمین → تنظیمات → «پنل پیامکی» کلید API و شناسه قالب «ارسال سریع» (پارامتر `CODE`) را وارد کنید. دکمه «پیامک آزمایشی» و «اعتبار پنل» صحت تنظیمات را بررسی می‌کند.
- **ربات بله**: توکن را در پنل ادمین ذخیره کنید، سپس با دکمه «تنظیم خودکار Webhook» در صفحه «ربات بله» آدرس webhook خودکار روی `https://<domain>/api/bale/webhook` تنظیم می‌شود.
- اولویت ارسال کد بازیابی رمز: **پیامک اول، بله fallback**.

---

## استقرار روی سرور (Production)

راهنمای کامل و گام‌به‌گام در **[DEPLOY.md](DEPLOY.md)** — شامل:

- نصب Gunicorn پشت Nginx با `gunicorn_conf.py`
- واحد systemd آماده (`deploy/tmdz.service`)
- نمونه پیکربندی Nginx با مسدودسازی پوشه‌های حساس (`deploy/nginx.conf`)
- گواهی SSL با certbot
- چک‌لیست امنیتی قبل از go-live

خلاصه:

```bash
git pull
env/bin/pip install -r requirements.txt
sudo systemctl restart tmdz
```

> Migration ها (`ALTER TABLE`) خودکار هنگام استارت اجرا می‌شوند — نیازی به دستور جدا نیست.

---

## بکاپ و کارهای زمان‌بندی‌شده

```bash
crontab -e

# بکاپ روزانه دیتابیس (نگهداری ۳۰ روز، PostgreSQL یا SQLite)
0 3 * * * cd /path/to/coop && ./scripts/backup_db.sh >> /var/log/tmdz-backup.log 2>&1

# علامت‌گذاری اقساط معوق + یادآوری پیامک/بله
0 8 * * * cd /path/to/coop && env/bin/python scripts/mark_overdue.py >> /var/log/tmdz-overdue.log 2>&1
```

---

## تست‌ها

```bash
python -m pytest tests/ -v

# با گزارش پوشش
pip install pytest-cov
python -m pytest tests/ --cov=app --cov-report=term-missing
```

مجموعه تست‌ها بیش از ۳۷۵ تست شامل: احراز هویت و کپچا، CSRF، محاسبه اقساط، نقل و انتقال دومرحله‌ای، حسابداری و تخصیص واریزی، کنترل دسترسی فایل، صفحه‌بندی/جستجو، و ماژول فرم‌ساز.

---

## استانداردهای توسعه

### افزودن ماژول API جدید

1. فایل جدید در `app/routes/api/` با یک `Blueprint`
2. ثبت در `app/routes/api/__init__.py` → `all_blueprints`
3. اگر ستون/جدول جدید لازم است، در `_migrate()` (`app/__init__.py`) اضافه کنید
4. تست بنویسید (`tests/test_security_and_finance.py` یا فایل مرتبط)

### قراردادها

- پیام‌های خطا فارسی و کاربرپسند
- endpoint های مدیریتی: `err = require_admin(); if err: return err` (یا `require_finance()`)
- Magic String ها از `app/constants.py`
- آپلود فایل از `app/utils/files.py` (اعتبارسنجی خودکار نوع/حجم)
- اسناد مالی هرگز حذف فیزیکی نمی‌شوند — فقط «ابطال» با ثبت دلیل

### وابستگی‌های اصلی

| کتابخانه | کاربرد |
|---|---|
| Flask, Flask-Login, Flask-WTF, Flask-Limiter | فریم‌ورک، احراز هویت، CSRF، rate limit |
| SQLAlchemy, psycopg2-binary | ORM و درایور PostgreSQL |
| openpyxl | Import/Export اکسل |
| Pillow | پردازش تصویر |
| requests | ارتباط با API بله و sms.ir |
| Gunicorn | سرور WSGI تولید |
