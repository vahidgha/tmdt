#!/usr/bin/env bash
# seed_default.sh — داده‌های پیش‌فرض سامانه (ادمین + تنظیمات) را می‌سازد
#
# اجرا:
#   bash seed_default.sh                  ← فقط ادمین و تنظیمات
#   bash seed_default.sh --with-samples   ← + داده‌های نمونه کامل

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ─── بارگذاری .env ────────────────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -o allexport
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +o allexport
    echo "✓ فایل .env بارگذاری شد"
else
    echo "⚠  فایل .env یافت نشد — از مقادیر پیش‌فرض استفاده می‌شود"
fi

WITH_SAMPLES="${1:-}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🌱 شروع seed داده‌های پیش‌فرض"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$SCRIPT_DIR"
python3 seed_default.py

if [ "${WITH_SAMPLES}" = "--with-samples" ]; then
    echo ""
    echo "  📦 بارگذاری داده‌های نمونه (اعضا، پروژه‌ها، اقساط)..."
    python3 seed.py
fi
