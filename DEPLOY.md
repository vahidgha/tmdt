# راهنمای استقرار (Production)

استقرار استاندارد: **Gunicorn** (اپ) پشت **Nginx** (reverse proxy + SSL)، مدیریت‌شده با **systemd**.

> ⚠️ هرگز در production با `python run.py` و `FLASK_DEBUG=1` اجرا نکنید — دیباگر Werkzeug کل کد و داده را افشا می‌کند.

---

## ۱. پیش‌نیازها روی سرور

```bash
sudo apt update
sudo apt install -y python3-venv nginx postgresql   # postgres اختیاری
```

## ۲. آماده‌سازی اپ

```bash
cd /home/admin/tmdz-app
python3 -m venv env
env/bin/pip install -r requirements.txt
```

## ۳. فایل `.env`

از `.env.example` کپی و مقادیر را پر کنید:

```bash
cp .env.example .env
# کلید امن بسازید:
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))" >> .env
```

حداقل متغیرهای لازم برای production:

```
SECRET_KEY=<کلید تصادفی ۶۴ کاراکتری>
DATABASE_URL=postgresql://user:pass@localhost:5432/tmdz
BEHIND_PROXY=1
SESSION_COOKIE_SECURE=1        # فقط وقتی HTTPS فعال است
BIND=127.0.0.1:8000
WEB_CONCURRENCY=3
# اختیاری: SMSIR_API_KEY، BALE_TOKEN، RATELIMIT_STORAGE_URI=redis://localhost:6379
```

Migration ها هنگام استارت خودکار اجرا می‌شوند (جدول‌ها و ستون‌های جدید ساخته می‌شوند).

## ۴. تست دستی Gunicorn

```bash
env/bin/gunicorn -c gunicorn_conf.py run:app
# در ترمینال دیگر:  curl -I http://127.0.0.1:8000/login
```

## ۵. systemd

```bash
sudo cp deploy/tmdz.service /etc/systemd/system/tmdz.service
# مسیرها/کاربر را در فایل مطابق سرور ویرایش کنید
sudo systemctl daemon-reload
sudo systemctl enable --now tmdz
sudo systemctl status tmdz
journalctl -u tmdz -f          # لاگ زنده
```

## ۶. Nginx + SSL

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/tmdz
sudo ln -s /etc/nginx/sites-available/tmdz /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d tmdz.ir -d www.tmdz.ir     # گواهی SSL رایگان
```

پس از فعال‌شدن HTTPS، مطمئن شوید `SESSION_COOKIE_SECURE=1` در `.env` هست و سرویس را ری‌استارت کنید.

## ۷. کارهای زمان‌بندی‌شده (cron)

```bash
crontab -e
# بکاپ روزانه ۳ صبح
0 3 * * * cd /home/admin/tmdz-app && ./scripts/backup_db.sh >> /var/log/tmdz-backup.log 2>&1
# علامت‌گذاری اقساط معوق + یادآوری، روزانه ۸ صبح
0 8 * * * cd /home/admin/tmdz-app && env/bin/python scripts/mark_overdue.py >> /var/log/tmdz-overdue.log 2>&1
```

---

## به‌روزرسانی نسخه

```bash
cd /home/admin/tmdz-app
git pull
env/bin/pip install -r requirements.txt   # اگر وابستگی جدید بود
sudo systemctl restart tmdz
```

## لاگ‌ها و خطاها

- لاگ خطای اپ: `logs/app.log` (چرخشی، ۵ فایل)
- لاگ سرویس: `journalctl -u tmdz`
- خطاهای ۵۰۰ به‌صورت خودکار برای ادمین‌های متصل به بله پیام می‌شوند.

## چک‌لیست امنیتی production

- [ ] `SECRET_KEY` تنظیم شده (ثابت، تصادفی)
- [ ] `FLASK_DEBUG` تنظیم **نشده**
- [ ] HTTPS فعال + `SESSION_COOKIE_SECURE=1`
- [ ] `BEHIND_PROXY=1`
- [ ] رمز پیش‌فرض `admin/admin123` تغییر کرده
- [ ] بکاپ خودکار فعال و تست‌شده (restore را یک‌بار امتحان کنید)
- [ ] پوشه‌های `logs/`, `backups/`, `static/uploads/` قابل نوشتن توسط کاربر سرویس
