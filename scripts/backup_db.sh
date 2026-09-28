#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# بکاپ خودکار دیتابیس — PostgreSQL یا SQLite + فایل‌های آپلود
#
# استفاده:
#   ./scripts/backup_db.sh                # بکاپ در ./backups
#   BACKUP_DIR=/mnt/backup ./scripts/backup_db.sh
#
# نصب cron (روزانه ساعت ۳ صبح):
#   crontab -e
#   0 3 * * * cd /home/admin/tmdz-app && ./scripts/backup_db.sh >> /var/log/tmdz-backup.log 2>&1
#
# متغیرها (اختیاری):
#   BACKUP_DIR   — مسیر ذخیره بکاپ‌ها          (پیش‌فرض: ./backups)
#   KEEP_DAYS    — چند روز بکاپ نگه داشته شود   (پیش‌فرض: 30)
#   DATABASE_URL — از .env خوانده می‌شود اگر ست نشده باشد
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"

# خواندن DATABASE_URL از .env در صورت نبود
if [ -z "${DATABASE_URL:-}" ] && [ -f .env ]; then
  DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2- || true)"
fi

mkdir -p "$BACKUP_DIR"

echo "── بکاپ $STAMP ─────────────────────────────"

# ── دیتابیس ──────────────────────────────────────────────────────────────────
if [[ "${DATABASE_URL:-}" == postgres* ]]; then
  OUT="$BACKUP_DIR/db_${STAMP}.dump"
  # pg_dump با فرمت custom — قابل restore با pg_restore
  pg_dump --format=custom --no-owner --dbname="$DATABASE_URL" --file="$OUT"
  echo "✅ PostgreSQL → $OUT ($(du -h "$OUT" | cut -f1))"
else
  DB_FILE="noyan.db"
  if [ -f "$DB_FILE" ]; then
    OUT="$BACKUP_DIR/db_${STAMP}.sqlite3"
    # .backup مطمئن‌تر از cp است (حین نوشتن هم consistent می‌ماند)
    if command -v sqlite3 >/dev/null 2>&1; then
      sqlite3 "$DB_FILE" ".backup '$OUT'"
    else
      python3 -c "import sqlite3; src=sqlite3.connect('$DB_FILE'); dst=sqlite3.connect('$OUT'); src.backup(dst); dst.close(); src.close()"
    fi
    gzip "$OUT"
    echo "✅ SQLite → ${OUT}.gz ($(du -h "${OUT}.gz" | cut -f1))"
  else
    echo "⚠️ نه DATABASE_URL پستگرس است نه $DB_FILE وجود دارد — بکاپ دیتابیس رد شد"
  fi
fi

# ── فایل‌های آپلود (هفته‌ای یک‌بار کامل — روزهای جمعه) ─────────────────────────
if [ "$(date +%u)" = "5" ] && [ -d static/uploads ]; then
  UP_OUT="$BACKUP_DIR/uploads_${STAMP}.tar.gz"
  tar -czf "$UP_OUT" static/uploads
  echo "✅ آپلودها → $UP_OUT ($(du -h "$UP_OUT" | cut -f1))"
fi

# ── پاک‌سازی بکاپ‌های قدیمی ──────────────────────────────────────────────────
DELETED=$(find "$BACKUP_DIR" -name 'db_*' -mtime +"$KEEP_DAYS" -print -delete | wc -l)
find "$BACKUP_DIR" -name 'uploads_*' -mtime +"$KEEP_DAYS" -delete || true
echo "🧹 $DELETED بکاپ قدیمی‌تر از $KEEP_DAYS روز حذف شد"
echo "── پایان ─────────────────────────────────────"

# ── راهنمای Restore ──────────────────────────────────────────────────────────
# PostgreSQL:
#   pg_restore --clean --no-owner --dbname="$DATABASE_URL" backups/db_XXXX.dump
# SQLite:
#   gunzip backups/db_XXXX.sqlite3.gz && cp backups/db_XXXX.sqlite3 noyan.db
