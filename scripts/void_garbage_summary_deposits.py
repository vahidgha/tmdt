#!/usr/bin/env python3
"""
پاک‌سازی اسناد واریز ساختگی که در نسخه‌ی قبلی import_legacy_data.py به‌اشتباه
از جدول خلاصه/گزارش مالی انتهای شیت «صورتحساب۱» به‌عنوان تراکنش واقعی وارد
شده بودند (نه یک اشتباه در بانک — یک باگ در وارد‌کردن که رفع شد، این اسکریپت
فقط عوارض آن روی داده‌ی از‌قبل‌واردشده را پاک می‌کند).

تشخیص: ردیف‌های خلاصه/گزارش، برخلاف هر تراکنش واقعی، ستون تاریخ خالی داشتند —
پس هر سند واریزِ source=bank_import با deposit_date خالی، قطعاً یکی از همین
ردیف‌های ساختگی است، نه یک تراکنش واقعی (تراکنش واقعی هرگز بدون تاریخ نیست).

اجرا:
    env/bin/python scripts/void_garbage_summary_deposits.py

ایمن برای اجرای چندباره — چیزی که قبلاً ابطال شده دوباره ابطال نمی‌شود.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

import app as app_pkg
from app import create_app
from app.models import DepositVoucher

db_session = None

REASON = ("ابطال خودکار — این سند در واقع یک تراکنش بانکی نبود، بلکه به‌اشتباه "
          "از جدول خلاصه/گزارش مالی انتهای فایل اکسل (نه از یک تراکنش واقعی) "
          "وارد شده بود؛ باگ import رفع شد، این ابطال فقط عوارض قبلی را جمع می‌کند.")


def main():
    global db_session
    app = create_app()
    db_session = app_pkg.db_session

    with app.app_context():
        bad = (db_session.query(DepositVoucher)
               .filter(DepositVoucher.source == "bank_import",
                       DepositVoucher.status == "active",
                       (DepositVoucher.deposit_date.is_(None)) | (DepositVoucher.deposit_date == ""))
               .all())

        if not bad:
            print("چیزی برای ابطال پیدا نشد.")
            return

        total = sum(v.amount for v in bad)
        print(f"{len(bad)} سند ساختگی پیدا شد — جمع مبلغ: {total:,} ریال")
        for v in bad:
            print(f"  سند #{v.number}: {v.amount:,} ریال — {v.description or v.payer_name}")

        for v in bad:
            v.status = "voided"
            v.void_reason = REASON
            v.voided_at = datetime.utcnow()
        db_session.commit()
        print(f"\n{len(bad)} سند ابطال شد. جمع واریزی‌های فعال اکنون {total:,} ریال کمتر خواهد بود.")


if __name__ == "__main__":
    main()
