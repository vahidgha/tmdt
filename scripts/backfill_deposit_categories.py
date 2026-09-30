#!/usr/bin/env python3
"""
اسناد واریزی که پیش از افزودن ستون category درون‌ریزی شده‌اند را بر اساس متن
توضیحات کدینگ می‌کند — سطرهایی که توضیحاتشان «سود» دارد (سود سپرده/سود پرداخت‌شده)
به category='bank_interest' تغییر می‌کنند؛ مابقی همان member_deposit پیش‌فرض می‌مانند.

این اسکریپت فقط رکوردهای از‌قبل‌موجود در دیتابیس را اصلاح می‌کند و به فایل اکسل
نیازی ندارد. برای وارد کردن اسناد هزینه‌ی کارمزد بانکی که قبلاً اصلاً وارد
نشده بودند، به‌جای این اسکریپت باید scripts/import_legacy_data.py دوباره روی
همان فایل اکسل اجرا شود (idempotent است — فقط ردیف‌های کارمزد جدید را اضافه
می‌کند).

اجرا:
    env/bin/python scripts/backfill_deposit_categories.py

ایمن برای اجرای چندباره.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_pkg
from app import create_app
from app.models import DepositVoucher

db_session = None


def main():
    global db_session
    app = create_app()
    db_session = app_pkg.db_session

    with app.app_context():
        candidates = (
            db_session.query(DepositVoucher)
            .filter(
                DepositVoucher.source == "bank_import",
                (DepositVoucher.category.is_(None)) | (DepositVoucher.category == "member_deposit"),
                DepositVoucher.description.isnot(None),
                DepositVoucher.description.contains("سود"),
            )
            .all()
        )

        if not candidates:
            print("چیزی برای اصلاح پیدا نشد.")
            return

        total = sum(v.amount for v in candidates)
        print(f"{len(candidates)} سند واریز با متن «سود» پیدا شد — جمع مبلغ: {total:,} ریال")
        for v in candidates:
            print(f"  سند #{v.number}: {v.amount:,} ریال — {v.description}")
            v.category = "bank_interest"

        db_session.commit()
        print(f"\n{len(candidates)} سند به کدینگ «سود بانکی» تغییر یافت.")


if __name__ == "__main__":
    main()
