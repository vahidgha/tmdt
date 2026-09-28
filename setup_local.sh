#!/usr/bin/env bash
# =============================================================
#  هیئت امنای مسکن دادگستری زنجان — Local Setup Script
#  نصب و راه‌اندازی کامل روی سیستم محلی
# =============================================================
set -e

# ─── رنگ‌ها ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC}  $*"; }
info() { echo -e "${CYAN}→${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "${RED}✗${NC}  $*"; exit 1; }
hdr()  { echo -e "\n${BOLD}${CYAN}══  $*  ══${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

hdr "هیئت امنای مسکن دادگستری زنجان — Local Setup"
echo -e "  دایرکتوری پروژه: ${BOLD}$SCRIPT_DIR${NC}"
echo ""

# ─── 1. بررسی Python ────────────────────────────────────────
hdr "1. بررسی Python"
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$($cmd --version 2>&1 | grep -o '[0-9]*\.[0-9]*\.[0-9]*' | head -1)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON="$cmd"
            ok "پایتون پیدا شد: $cmd ($VER)"
            break
        fi
    fi
done
[ -z "$PYTHON" ] && fail "پایتون ۳.۹ یا بالاتر پیدا نشد. لطفاً python3 نصب کنید."

# ─── 2. Virtual Environment ─────────────────────────────────
hdr "2. Virtual Environment"
VENV_DIR="$SCRIPT_DIR/venv"

if [ -d "$VENV_DIR" ]; then
    ok "venv قبلاً ساخته شده"
else
    info "ساخت venv ..."
    $PYTHON -m venv "$VENV_DIR"
    ok "venv ساخته شد: $VENV_DIR"
fi

# Activate
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
elif [ -f "$VENV_DIR/Scripts/activate" ]; then
    source "$VENV_DIR/Scripts/activate"
else
    fail "نمی‌توان venv را فعال کرد"
fi
ok "venv فعال شد"

PIP="$VENV_DIR/bin/pip"
PYTHON_BIN="$VENV_DIR/bin/python"
[ ! -f "$PYTHON_BIN" ] && PYTHON_BIN="$VENV_DIR/Scripts/python"

# ─── 3. نصب وابستگی‌ها ─────────────────────────────────────
hdr "3. نصب وابستگی‌ها"
info "نصب requirements.txt ..."
$PIP install --quiet --upgrade pip
$PIP install --quiet -r requirements.txt
ok "همه وابستگی‌ها نصب شدند"

# نصب pytest برای اجرای تست‌ها
$PIP install --quiet pytest pytest-cov
ok "pytest نصب شد"

# ─── 4. ایجاد فولدرهای لازم ────────────────────────────────
hdr "4. ساختار فولدر"
mkdir -p static/uploads
mkdir -p static/uploads/projects
mkdir -p static/uploads/members
mkdir -p static/uploads/receipts
mkdir -p static/uploads/slides
mkdir -p static/icons
ok "فولدرهای uploads ساخته شدند"

# ساخت آیکون‌های PWA
if [ ! -f "static/icons/icon-192.png" ]; then
    info "ساخت آیکون‌های PWA ..."
    $PYTHON_BIN -c "
from PIL import Image, ImageDraw
import os
os.makedirs('static/icons', exist_ok=True)
def make_icon(size, path):
    img = Image.new('RGB', (size, size), '#0E1B32')
    draw = ImageDraw.Draw(img)
    s = size
    draw.ellipse([s*.08,s*.08,s*.92,s*.92], fill='#1A2E50')
    draw.polygon([(s*.2,s*.52),(s*.5,s*.22),(s*.8,s*.52)], fill='#C8A456')
    draw.rectangle([s*.28,s*.52,s*.72,s*.76], fill='#C8A456')
    draw.rectangle([s*.42,s*.60,s*.58,s*.76], fill='#0E1B32')
    img.save(path, 'PNG')
make_icon(192, 'static/icons/icon-192.png')
make_icon(512, 'static/icons/icon-512.png')
make_icon(180, 'static/icons/apple-touch-icon.png')
" 2>/dev/null && ok "آیکون‌های PWA ساخته شدند" || warn "ساخت آیکون ناموفق (pillow نصب نیست؟)"
else
    ok "آیکون‌های PWA از قبل موجودند"
fi

# ─── 5. فایل .env ───────────────────────────────────────────
hdr "5. تنظیمات محیطی"
if [ ! -f ".env" ]; then
    cat > .env <<'ENVEOF'
# ── App Config ──────────────────────────────────────────────
SECRET_KEY=change-me-in-production-$(openssl rand -hex 16 2>/dev/null || echo "local-secret-key-12345")
DATABASE_URL=sqlite:///noyan.db
UPLOAD_FOLDER=static/uploads
MAX_CONTENT_MB=50

# ── در production این را تغییر دهید ─────────────────────────
FLASK_ENV=development
FLASK_DEBUG=1
ENVEOF
    ok ".env ساخته شد"
else
    ok ".env از قبل موجود است"
fi

# ─── 6. راه‌اندازی دیتابیس ─────────────────────────────────
hdr "6. دیتابیس"
info "ایجاد جداول و داده‌های اولیه ..."
$PYTHON_BIN -c "
from app import create_app, db
app = create_app()
with app.app_context():
    db.create_all()
    print('  جداول ساخته شدند')
"
ok "دیتابیس آماده است"

# Seed اگر seed.py وجود دارد
if [ -f "seed.py" ]; then
    info "اجرای seed.py ..."
    $PYTHON_BIN seed.py 2>/dev/null && ok "seed اجرا شد" || warn "seed با خطا مواجه شد (ممکن است داده‌ها از قبل موجود باشند)"
fi

# ─── 7. اجرای تست‌ها ────────────────────────────────────────
hdr "7. اجرای تست‌ها"
echo ""

if [ "${1}" == "--skip-tests" ]; then
    warn "تست‌ها رد شدند (--skip-tests)"
else
    info "در حال اجرای سوئیت تست کامل ..."
    echo ""

    if $PYTHON_BIN -m pytest tests/test_full.py \
        -v \
        --tb=short \
        --no-header \
        -q \
        2>&1 | tee /tmp/test_output.txt; then
        echo ""
        ok "همه تست‌ها با موفقیت گذشتند ✓"
        TEST_PASSED=true
    else
        echo ""
        FAILED=$(grep -c "FAILED" /tmp/test_output.txt 2>/dev/null || echo "?")
        warn "$FAILED تست ناموفق بودند — برای جزئیات: pytest tests/test_full.py -v"
        TEST_PASSED=false
    fi
    echo ""
fi

# ─── 8. خلاصه وضعیت ────────────────────────────────────────
hdr "8. خلاصه"
echo ""
echo -e "  ${BOLD}آدرس برنامه:${NC}     http://localhost:5000"
echo -e "  ${BOLD}نام کاربری:${NC}      admin"
echo -e "  ${BOLD}رمز عبور:${NC}        admin123"
echo -e "  ${BOLD}دیتابیس:${NC}         noyan.db (SQLite)"
echo -e "  ${BOLD}آپلودها:${NC}         static/uploads/"
echo ""
echo -e "  ${BOLD}دستورات مفید:${NC}"
echo -e "    اجرای برنامه:   ${CYAN}python run.py${NC}"
echo -e "    اجرای تست‌ها:   ${CYAN}pytest tests/test_full.py -v${NC}"
echo -e "    گزارش پوشش:    ${CYAN}pytest tests/ --cov=app --cov-report=html${NC}"
echo ""

# ─── 9. راه‌اندازی سرور ────────────────────────────────────
hdr "9. راه‌اندازی سرور"
if [ "${1}" == "--no-server" ] || [ "${2}" == "--no-server" ]; then
    warn "سرور راه‌اندازی نشد (--no-server)"
    echo ""
    echo -e "  برای راه‌اندازی دستی: ${CYAN}source venv/bin/activate && python run.py${NC}"
else
    echo ""
    echo -e "  ${GREEN}${BOLD}سرور در حال راه‌اندازی...${NC}"
    echo -e "  ${CYAN}برای متوقف‌کردن: Ctrl+C${NC}"
    echo ""
    $PYTHON_BIN run.py
fi
