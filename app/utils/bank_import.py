"""واردات صورت‌حساب خام بانکی و تطبیق خودکار واریزی‌ها با شناسه واریز اعضا.

فایل ورودی، خروجی مستقیم سامانه بانکداری سازمانی است (مثلاً بانک ملی):
ردیف، تاریخ، زمان، مبلغ واریز، مبلغ برداشت، مانده، کد شعبه، نام شعبه،
شماره پیگیری، شرح تراکنش، توضیحات، توضیحات اضافی، توضیحات کاربر، کانال.

منطق تطبیق: عدد «شناسه واریز» عضو (User.deposit_id) معمولاً داخل ستون‌های
توضیحات/شرح تراکنش هر تراکنش واریزی درج شده — تمام رشته‌های عددی ۸ رقمی به بالا
از این ستون‌ها استخراج و با شناسه واریزهای ثبت‌شده اعضا مقایسه می‌شود.
"""
import re

_DIGITS_RE = re.compile(r"\d{8,}")


def normalize_digits_only(value) -> str:
    """هر مقداری را به رشته‌ای فقط‌شامل ارقام (انگلیسی) تبدیل می‌کند."""
    return re.sub(r"\D", "", str(value or ""))


def cell_str(value) -> str:
    """مقدار یک سلول اکسل را به رشته قابل‌مقایسه تبدیل می‌کند (اعداد بزرگ float به int)."""
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value).strip()


def cell_amount(value) -> int:
    """مبلغ ریالی را از سلول استخراج می‌کند؛ '-' یا خالی یعنی صفر."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "")
    if not s or s == "-":
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


# نگاشت برچسب ستون هدر (زیررشته) → کلید داخلی — ترتیب مهم نیست چون هر سلول هدر
# فقط یک‌بار و با اولین برچسب منطبق شناسایی می‌شود.
_SINGLE_COL_LABELS = [
    ("deposit_amount",     "مبلغ واریز"),
    ("withdrawal_amount",  "مبلغ برداشت"),
    ("balance",            "مانده"),
    ("branch_code",        "کد شعبه"),
    ("branch_name",        "نام شعبه"),
    ("reference_no",       "شماره پیگیری"),
    ("channel",            "کانال"),
    ("time",               "زمان"),
    ("date",               "تاریخ"),
]
_DESC_LABELS = ("شرح تراکنش", "توضیحات")


def find_bank_header(ws):
    """
    ردیف هدر صورت‌حساب را پیدا می‌کند و شاخص ستون‌ها را برمی‌گرداند.
    خروجی: (row_index یا None, dict شامل کلیدهای _SINGLE_COL_LABELS + 'desc_cols' (لیست اندیس)).
    """
    for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
        cells = [str(c or "").strip() for c in row]
        if not any("مبلغ واریز" in c for c in cells):
            continue

        idx = {k: None for k, _ in _SINGLE_COL_LABELS}
        desc_cols = []
        for ci, c in enumerate(cells):
            matched = False
            for key, label in _SINGLE_COL_LABELS:
                if idx[key] is None and label in c:
                    idx[key] = ci
                    matched = True
                    break
            if not matched and any(lbl in c for lbl in _DESC_LABELS):
                desc_cols.append(ci)
        idx["desc_cols"] = desc_cols
        return r_idx, idx
    return None, None


def extract_deposit_id_candidates(text: str):
    """همه رشته‌های عددی ۸ رقمی‌به‌بالا را از یک متن استخراج می‌کند."""
    return _DIGITS_RE.findall(text or "")


def build_deposit_id_map(users) -> dict:
    """نگاشت شناسه‌واریز نرمال‌شده → کاربر، از روی لیست کاربران دارای deposit_id."""
    mapping = {}
    for u in users:
        norm = normalize_digits_only(u.deposit_id)
        if norm:
            mapping[norm] = u
    return mapping
