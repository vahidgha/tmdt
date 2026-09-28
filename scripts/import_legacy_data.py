#!/usr/bin/env python3
"""
درون‌ریزی یک‌باره داده‌های واقعی سازمان از فایل اکسل قدیمی: اطلاعات پرسنل
(شیت «شناسه دوم»)، صورت‌حساب بانکی خام (شیت «صورتحساب») و پرداخت‌های پیمانکار
(شیت «پرداختی»).

اجرا:
    env/bin/python scripts/import_legacy_data.py /path/to/file.xlsx \
        --account-holder "نام صاحب حساب" --bank-name "ملی" --account-number "236526572001"

ایمن برای اجرای چندباره است — اعضا بر اساس کد ملی/شناسه واریز، و اسناد بر اساس
حساب+شماره پیگیری+تاریخ+مبلغ، در صورت وجود قبلی دوباره ساخته نمی‌شوند.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import load_workbook
from sqlalchemy import func
from werkzeug.security import generate_password_hash

import app as app_pkg
from app import create_app
from app.models import CoopAccount, DepositVoucher, ExpenseVoucher, User
from app.utils.bank_import import build_deposit_id_map, cell_amount, cell_str

# db_session روی ماژول app فقط داخل create_app() مقداردهی می‌شود (قبل از آن None
# است) — پس این نام را همین‌جا با مقدار None می‌سازیم و main() بعد از فراخوانی
# create_app() با global آن را به‌روز می‌کند؛ توابع زیر همیشه از همین نام ماژولی
# (تازه‌شده) استفاده می‌کنند، نه یک ارجاع کش‌شده‌ی قدیمی.
db_session = None


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _pad10(v) -> str:
    d = _digits(v)
    return d.zfill(10) if d else ""


def _cell(row, i):
    return row[i] if i is not None and i < len(row) and row[i] is not None else None


def _enrichment_from_id_sheet(wb, sheet_name="شناسه دوم"):
    """
    نگاشت کمکی کدپرسنلی → (شماره همراه، واحد سازمانی) از شیت کوچک «شناسه دوم».
    این شیت فقط زیرمجموعه‌ای از اعضاست؛ صرفاً برای تکمیل دو فیلدی که در
    «صورتحساب۱» نیست استفاده می‌شود، نه به‌عنوان منبع اصلی اعضا.
    """
    out = {}
    if sheet_name not in wb.sheetnames:
        return out
    ws = wb[sheet_name]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not any(row):
            continue
        personnel_code = _digits(_cell(row, 5))
        if not personnel_code:
            continue
        phone = _digits(_cell(row, 8))
        if phone and not phone.startswith("0"):
            phone = "0" + phone
        org_unit = str(_cell(row, 10) or "").strip()
        out[personnel_code] = (phone, org_unit)
    return out


def _iter_statement1_rows(ws):
    """
    ردیف‌های شیت «صورتحساب۱» (نسخه از قبل تطبیق‌داده‌شده با هویت اعضا) را با
    نام‌گذاری ستون ثابت برمی‌گرداند — ستون‌های این شیت هدر یکتا ندارند (چند
    ستون تکراری «توضیحات اضافی»/«مبلغ واریزی»)، پس با اندیس ثابت (بر اساس
    بازرسی مستقیم فایل واقعی) خوانده می‌شود، نه تطبیق برچسب هدر.
    """
    for row in ws.iter_rows(min_row=9, values_only=True):
        if not row or not any(row):
            continue
        yield {
            "date": cell_str(_cell(row, 2)).strip(),
            "time": cell_str(_cell(row, 3)).strip(),
            "deposit_amount": cell_amount(_cell(row, 4)),
            "balance": cell_amount(_cell(row, 6)) or None,
            "branch_code": cell_str(_cell(row, 7)),
            "branch_name": cell_str(_cell(row, 8)),
            "reference_no": cell_str(_cell(row, 9)),
            "tx_type": cell_str(_cell(row, 10)),
            "desc_cols": [cell_str(_cell(row, i)) for i in (11, 12, 13)],
            "channel": cell_str(_cell(row, 14)),
            "deposit_id": _digits(_cell(row, 16)),
            "personnel_code": _digits(_cell(row, 17)),
            "first_name": str(_cell(row, 18) or "").strip(),
            "last_name": str(_cell(row, 19) or "").strip(),
            "national_code": _pad10(_cell(row, 20)),
        }


def import_members(wb, statement1_sheet="صورتحساب1"):
    """
    اعضا را از ستون‌های از‌قبل‌تطبیق‌یافته‌ی شیت «صورتحساب۱» می‌سازد (کدپرسنلی،
    نام، نام خانوادگی، کدملی، شناسه واریز) — این شیت خروجی سامانه‌ی خود بانک/
    سازمان است و صدها نفر بیشتر از شیت «شناسه دوم» (که فقط زیرمجموعه‌ای کوچک
    است) پوشش می‌دهد. شماره همراه و واحد سازمانی، در صورت وجود، از «شناسه دوم»
    تکمیل می‌شود.
    """
    if statement1_sheet not in wb.sheetnames:
        print(f"  ⚠️  شیت «{statement1_sheet}» پیدا نشد — رد شد.")
        return 0, 0

    enrichment = _enrichment_from_id_sheet(wb)
    ws = wb[statement1_sheet]

    # یک عضو ممکن است چند ردیف تراکنش داشته باشد — اولین مقدار هر کدپرسنلی کافی است
    by_personnel = {}
    for r in _iter_statement1_rows(ws):
        pc = r["personnel_code"]
        if pc and pc not in by_personnel:
            by_personnel[pc] = r

    created = updated = 0
    default_pw = os.environ.get("DEFAULT_NEW_OWNER_PASSWORD", "changeme123")
    # هش رمز پیش‌فرض یک‌بار محاسبه می‌شود، نه به ازای هر عضو — الگوریتم هش رمز
    # عمداً کند است (برای امنیت)، و روی هزاران عضو با رمز یکسان و موقت (که باید
    # در اولین ورود عوض شود) محاسبه‌ی جداگانه فقط زمان درون‌ریزی را طولانی می‌کند
    default_pw_hash = generate_password_hash(default_pw)

    # همه‌ی اعضای موجود را یک‌بار پیش‌بارگذاری می‌کنیم — به‌جای یک کوئری
    # جداگانه به ازای هر ردیف (که با autoflush پیش‌فرض SQLAlchemy روی چند هزار
    # شیء در حال انتظار درون session به‌شدت کند می‌شود، تقریباً O(n^2))
    existing_users = db_session.query(User).all()
    used_usernames = {u.username for u in existing_users}
    by_pc = {u.personnel_code: u for u in existing_users if u.personnel_code}
    by_nat = {u.national_code: u for u in existing_users if u.national_code}
    by_dep = {u.deposit_id: u for u in existing_users if u.deposit_id}
    claimed_deposit_ids = set(by_dep.keys())
    dep_collisions = []

    for personnel_code, r in by_personnel.items():
        national_code = r["national_code"]
        deposit_id = r["deposit_id"]
        phone, org_unit = enrichment.get(personnel_code, ("", ""))

        existing = (by_pc.get(personnel_code)
                    or (national_code and by_nat.get(national_code))
                    or (deposit_id and by_dep.get(deposit_id)))

        if existing:
            existing.personnel_code = existing.personnel_code or personnel_code
            existing.national_code = existing.national_code or (national_code or None)
            existing.deposit_id = existing.deposit_id or (deposit_id or None)
            existing.org_unit = existing.org_unit or (org_unit or None)
            existing.phone = existing.phone or (phone or None)
            updated += 1
            continue

        # چند کدپرسنلی نادر در داده منبع «شناسه واریز» یکسان دارند (خطای داده
        # منبع، نه سیستم ما) — چون این ستون باید یکتا باشد، برای نفر دوم به بعد
        # خالی می‌گذاریم تا بعداً دستی بررسی و اصلاح شود
        if deposit_id and deposit_id in claimed_deposit_ids:
            dep_collisions.append((personnel_code, deposit_id))
            deposit_id = ""
        elif deposit_id:
            claimed_deposit_ids.add(deposit_id)

        base_username = personnel_code or national_code or deposit_id
        username = base_username
        i = 1
        while username in used_usernames:
            i += 1
            username = f"{base_username}-{i}"
        used_usernames.add(username)

        db_session.add(User(
            username=username,
            password_hash=default_pw_hash,
            role="member",
            first_name=r["first_name"] or "-",
            last_name=r["last_name"] or "-",
            national_code=national_code or None,
            personnel_code=personnel_code or None,
            deposit_id=deposit_id or None,
            phone=phone or None,
            org_unit=org_unit or None,
            active=True,
            profile_complete=True,
        ))
        created += 1

    db_session.commit()
    if dep_collisions:
        print(f"  ⚠️  {len(dep_collisions)} شناسه واریز تکراری در داده منبع — عضو دوم بدون شناسه واریز ساخته شد:")
        for pc, dep in dep_collisions:
            print(f"      کدپرسنلی {pc} (شناسه واریز تکراری: {dep})")
    return created, updated


def get_or_create_account(holder_name, bank_name, account_number):
    acc = None
    if account_number:
        acc = db_session.query(CoopAccount).filter_by(account_number=account_number).first()
    if acc:
        return acc
    acc = CoopAccount(holder_name=holder_name, bank_name=bank_name,
                       account_number=account_number, active=True)
    db_session.add(acc)
    db_session.commit()
    return acc


def import_deposits(wb, account, statement1_sheet="صورتحساب1"):
    """
    واریزی‌ها را از «صورتحساب۱» می‌خواند و مستقیماً از روی ستون کدپرسنلی
    (که در همان شیت از قبل تطبیق داده شده) عضو را پیدا می‌کند — نیازی به
    حدس‌زدن از روی متن توضیحات نیست چون این شیت خودش نتیجه‌ی آن تطبیق است.
    """
    if statement1_sheet not in wb.sheetnames:
        print(f"  ⚠️  شیت «{statement1_sheet}» پیدا نشد — رد شد.")
        return 0, 0, 0, 0
    ws = wb[statement1_sheet]

    users_by_personnel = {
        u.personnel_code: u
        for u in db_session.query(User).filter(User.personnel_code.isnot(None)).all()
    }
    dep_map = build_deposit_id_map(
        db_session.query(User).filter(User.deposit_id.isnot(None), User.deposit_id != "").all()
    )
    last_no = db_session.query(func.max(DepositVoucher.number)).scalar() or 1000
    matched = unmatched = dup = zero = 0

    # کلیدهای اسناد از‌قبل‌موجود این حساب — یک‌بار پیش‌بارگذاری به‌جای یک کوئری
    # به ازای هر ردیف (همان دلیل عملکردی import_members)
    existing_keys = set(
        db_session.query(DepositVoucher.reference_no, DepositVoucher.deposit_date,
                         DepositVoucher.deposit_time, DepositVoucher.amount)
        .filter_by(account_id=account.id).all()
    )

    for r in _iter_statement1_rows(ws):
        amount = r["deposit_amount"]
        if amount <= 0:
            zero += 1
            continue

        deposit_date = r["date"]
        deposit_time = r["time"]
        reference_no = r["reference_no"]
        desc_raw = " ".join(filter(None, [r["tx_type"], *r["desc_cols"]]))

        key = (reference_no, deposit_date, deposit_time, amount)
        if key in existing_keys:
            dup += 1
            continue
        existing_keys.add(key)

        user = users_by_personnel.get(r["personnel_code"]) or dep_map.get(r["deposit_id"])

        last_no += 1
        db_session.add(DepositVoucher(
            number=last_no,
            user_id=user.id if user else None,
            payer_name="" if user else (desc_raw[:120] or "نامشخص"),
            account_id=account.id,
            amount=amount,
            deposit_date=deposit_date,
            deposit_time=deposit_time,
            method="cash" if "نقد" in desc_raw else "transfer",
            reference_no=reference_no,
            description=desc_raw or None,
            source="bank_import",
            branch_code=r["branch_code"],
            branch_name=r["branch_name"],
            channel=r["channel"],
            bank_balance_after=r["balance"],
        ))
        if user:
            matched += 1
        else:
            unmatched += 1

    db_session.commit()
    return matched, unmatched, dup, zero


def import_expenses(wb, account, sheet_name="پرداختی"):
    if sheet_name not in wb.sheetnames:
        return 0
    ws = wb[sheet_name]
    last_no = db_session.query(func.max(ExpenseVoucher.number)).scalar() or 1000
    created = 0
    header_seen = False

    for row in ws.iter_rows(min_row=1, values_only=True):
        vals = list(row)
        if not header_seen:
            if any(str(c or "").strip() == "ردیف" for c in vals):
                header_seen = True
            continue
        if not vals or vals[0] in (None, "جمع"):
            continue

        ref_no = cell_str(_cell(vals, 1))
        spend_date = cell_str(_cell(vals, 2)).strip()
        amount = cell_amount(_cell(vals, 3))
        desc = cell_str(_cell(vals, 4))
        if amount <= 0 or not spend_date:
            continue

        exists = db_session.query(ExpenseVoucher).filter_by(
            account_id=account.id, reference_no=ref_no, spend_date=spend_date, amount=amount,
        ).first()
        if exists:
            continue

        last_no += 1
        db_session.add(ExpenseVoucher(
            number=last_no, account_id=account.id, category="contractor",
            payee="ستاد اجرایی فرمان امام", amount=amount, spend_date=spend_date,
            method="cheque", reference_no=ref_no, description=desc or None,
        ))
        created += 1

    db_session.commit()
    return created


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xlsx_path")
    ap.add_argument("--account-holder", default="حساب اصلی پروژه")
    ap.add_argument("--account-number", default="")
    ap.add_argument("--bank-name", default="")
    args = ap.parse_args()

    global db_session
    app = create_app()
    db_session = app_pkg.db_session
    with app.app_context():
        wb = load_workbook(args.xlsx_path, data_only=True)

        print("\U0001F4E5 درون‌ریزی اعضا...")
        created, updated = import_members(wb)
        print(f"  عضو جدید: {created} — به‌روزرسانی‌شده: {updated}")

        account = get_or_create_account(args.account_holder, args.bank_name, args.account_number)
        print(f"\U0001F4E5 درون‌ریزی واریزی‌ها (حساب: {account.holder_name})...")
        matched, unmatched, dup, zero = import_deposits(wb, account)
        print(f"  تطبیق‌یافته: {matched} — بدون تطبیق: {unmatched} — تکراری نادیده‌گرفته‌شده: {dup} — ردیف صفر/برداشت: {zero}")

        print("\U0001F4E5 درون‌ریزی پرداخت‌های پیمانکار...")
        exp_created = import_expenses(wb, account)
        print(f"  سند هزینه جدید: {exp_created}")


if __name__ == "__main__":
    main()
