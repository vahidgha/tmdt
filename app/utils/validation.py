"""اعتبارسنجی ورودی‌های کاربر — قبل از رسیدن به دیتابیس"""
import re

# (فیلد، حداکثر طول، برچسب فارسی)
_USER_FIELD_LIMITS = [
    ("username",        80,  "نام کاربری"),
    ("first_name",      60,  "نام"),
    ("last_name",       60,  "نام خانوادگی"),
    ("national_code",   10,  "کد ملی"),
    ("gender",          10,  "جنسیت"),
    ("id_number",       20,  "شماره شناسنامه"),
    ("phone",           15,  "موبایل"),
    ("emergency_phone", 15,  "تلفن اضطراری"),
    ("father_name",     80,  "نام پدر"),
    ("birth_date",      20,  "تاریخ تولد"),
    ("birth_place",     60,  "محل تولد"),
    ("marital_status",  20,  "وضعیت تاهل"),
    ("landline",        15,  "تلفن ثابت"),
    ("postal_code",     10,  "کد پستی"),
    ("occupation",      80,  "شغل"),
    ("email",           120, "ایمیل"),
    ("bank_name",       60,  "نام بانک"),
    ("account_number",  30,  "شماره حساب"),
    ("iban",            30,  "شماره شبا"),
]

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_digits(value: str) -> str:
    """ارقام فارسی/عربی را به انگلیسی تبدیل می‌کند."""
    return (value or "").translate(_PERSIAN_DIGITS)


def validate_user_fields(data: dict) -> str | None:
    """
    فیلدهای کاربر را بررسی می‌کند و در صورت خطا پیام فارسی برمی‌گرداند.
    ارقام فارسی فیلدهای عددی را همان‌جا در data نرمال می‌کند.
    None یعنی همه‌چیز معتبر است.
    """
    # نرمال‌سازی ارقام فارسی در فیلدهای عددی
    for f in ("national_code", "phone", "emergency_phone", "landline",
              "postal_code", "id_number", "account_number", "iban"):
        if data.get(f):
            data[f] = normalize_digits(str(data[f]).strip())

    # بررسی طول همه فیلدها (جلوگیری از خطای دیتابیس VARCHAR)
    for field, max_len, label in _USER_FIELD_LIMITS:
        val = data.get(field)
        if val and len(str(val)) > max_len:
            return f"{label} نباید بیشتر از {max_len} کاراکتر باشد."

    # قواعد اختصاصی
    nat = data.get("national_code")
    if nat and not re.fullmatch(r"\d{10}", nat):
        return "کد ملی باید دقیقاً ۱۰ رقم باشد."

    postal = data.get("postal_code")
    if postal and not re.fullmatch(r"\d{10}", postal):
        return "کد پستی باید دقیقاً ۱۰ رقم باشد."

    phone = data.get("phone")
    if phone and not re.fullmatch(r"0\d{10}", phone):
        return "شماره موبایل باید ۱۱ رقم و با ۰ شروع شود. مثال: 09121234567"

    return None
