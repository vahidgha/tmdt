#!/usr/bin/env bash
# نصب سریع (Quickstart) روی یک سرور اوبونتو/دبیان تازه — برای اولین بار دیدن
# سایت با یک ساب‌دامین. برای production واقعی با بار زیاد، بعداً طبق DEPLOY.md
# به PostgreSQL مهاجرت کنید (این اسکریپت پیش‌فرض از SQLite استفاده می‌کند تا
# سریع‌ترین راه برای بالا آوردن سایت باشد).
#
# اجرا (روی خود سرور، با کاربر دارای sudo):
#   curl -fsSL https://raw.githubusercontent.com/vahidgha/tmdt/master/deploy/quickstart.sh -o quickstart.sh
#   chmod +x quickstart.sh
#   sudo ./quickstart.sh your-subdomain.example.com
#
# بعد از اجرا:
#   - سایت پشت nginx روی پورت 80 بالا می‌آید (HTTP)
#   - برای HTTPS: sudo certbot --nginx -d your-subdomain.example.com
#   - ورود ادمین: admin / admin123 — حتماً بلافاصله عوض کنید (پنل → ویرایش پروفایل)
#
# داده واقعی اعضا/واریزی‌ها را جدا وارد کنید (بعد از این اسکریپت):
#   sudo -u APP_USER env/bin/python scripts/import_legacy_data.py /path/to/file.xlsx \
#     --account-holder "..." --bank-name "..." --account-number "..."

set -euo pipefail

DOMAIN="${1:?استفاده: sudo ./quickstart.sh your-subdomain.example.com}"
APP_USER="${APP_USER:-$(logname 2>/dev/null || echo "${SUDO_USER:-$USER}")}"
APP_DIR="${APP_DIR:-/home/$APP_USER/tmdt-app}"
REPO_URL="${REPO_URL:-https://github.com/vahidgha/tmdt.git}"
SERVICE_NAME="tmdt"

if [ "$(id -u)" -ne 0 ]; then
  echo "این اسکریپت باید با sudo اجرا شود." >&2
  exit 1
fi

# --- سرور ممکن است اپ‌های دیگری هم داشته باشد — قبل از هر تغییری بررسی می‌کنیم
# که با آن‌ها تصادم نکنیم (پورت گونیکورن، فایل‌های nginx فقط با نام مخصوص خودمان) ---
echo "==> بررسی پیش از نصب (سرویس‌های دیگر دست‌نخورده می‌مانند)..."
if [ -f "/etc/nginx/sites-available/${SERVICE_NAME}" ] || [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
  echo "    توجه: به‌نظر می‌رسد قبلاً یک‌بار این اسکریپت اجرا شده — فایل‌های همین اپ آپدیت می‌شوند، نه اپ‌های دیگر."
fi

BIND_PORT=8000
while ss -Htln "sport = :$BIND_PORT" 2>/dev/null | grep -q .; do
  BIND_PORT=$((BIND_PORT + 1))
done
echo "    پورت داخلی آزاد برای gunicorn: 127.0.0.1:$BIND_PORT"

if ss -Htln 'sport = :80' 2>/dev/null | grep -q .; then
  if ! systemctl is-active --quiet nginx 2>/dev/null; then
    echo "خطا: پورت 80 توسط یک سرویس دیگر (نه nginx) اشغال شده — برای اینکه اپ دیگری روی این سرور خراب نشود، متوقف شدم." >&2
    echo "      خروجی 'ss -tlnp | grep :80' را بررسی کن." >&2
    exit 1
  fi
  echo "    nginx از قبل روی پورت 80 هست — فقط یک server block جدید برای $DOMAIN اضافه می‌کنیم، سایت‌های دیگرش دست‌نخورده می‌مانند."
fi

echo "==> نصب پیش‌نیازها (سرویس‌های موجود را دست نمی‌زند)..."
apt update -y
apt install -y python3-venv python3-pip nginx git

echo "==> کلون/به‌روزرسانی ریپو در $APP_DIR (کاربر: $APP_USER)..."
if [ -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull
else
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi

echo "==> ساخت virtualenv و نصب وابستگی‌ها..."
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/env"
sudo -u "$APP_USER" "$APP_DIR/env/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/env/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> ساخت .env..."
if [ ! -f "$APP_DIR/.env" ]; then
  SECRET_KEY="$(sudo -u "$APP_USER" "$APP_DIR/env/bin/python" -c "import secrets; print(secrets.token_hex(32))")"
  cat > "$APP_DIR/.env" <<EOF
SECRET_KEY=$SECRET_KEY
DATABASE_URL=sqlite:///$APP_DIR/tmdt.db
BEHIND_PROXY=1
SESSION_COOKIE_SECURE=0
BIND=127.0.0.1:$BIND_PORT
WEB_CONCURRENCY=2
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
SITE_TITLE=سامانه مدیریت اعضا و امور مالی
EOF
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  echo "    .env ساخته شد — SESSION_COOKIE_SECURE بعد از فعال‌سازی HTTPS باید 1 شود."
else
  echo "    .env از قبل هست — دست نخورد."
fi

echo "==> ساخت جدول‌ها و ادمین پیش‌فرض (اولین اجرای اپ)..."
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && set -a && source .env && set +a && env/bin/python -c 'from app import create_app; create_app()'"

echo "==> systemd service..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=TMDT (Gunicorn)
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/env/bin/gunicorn -c gunicorn_conf.py run:app
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

echo "==> nginx..."
cat > "/etc/nginx/sites-available/${SERVICE_NAME}" <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 60M;

    location /static/ {
        alias $APP_DIR/static/;
        expires 7d;
        access_log off;
    }
    location ~ ^/static/uploads/(requests|payments|member_docs|marketplace)/ {
        deny all;
        return 403;
    }
    location / {
        proxy_pass http://127.0.0.1:$BIND_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 90s;
    }
}
EOF
ln -sf "/etc/nginx/sites-available/${SERVICE_NAME}" "/etc/nginx/sites-enabled/${SERVICE_NAME}"
nginx -t
systemctl reload nginx

echo ""
echo "=================================================================="
echo " تمام شد. سایت باید روی http://$DOMAIN بالا باشد (بعد از این‌که DNS"
echo " ساب‌دامین را به آی‌پی همین سرور اشاره داد)."
echo ""
echo " برای HTTPS:  sudo apt install -y certbot python3-certbot-nginx"
echo "              sudo certbot --nginx -d $DOMAIN"
echo "              (بعدش SESSION_COOKIE_SECURE=1 را در .env بگذارید و: sudo systemctl restart $SERVICE_NAME)"
echo ""
echo " وضعیت سرویس: sudo systemctl status $SERVICE_NAME"
echo " لاگ زنده:    sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo " ورود ادمین:  admin / admin123  — همین الان از پنل عوضش کنید."
echo "=================================================================="
