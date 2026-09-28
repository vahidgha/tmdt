"""تبدیل و مقایسه تاریخ شمسی — بدون وابستگی خارجی"""
from datetime import date


def gregorian_to_jalali(gy: int, gm: int, gd: int):
    """میلادی → شمسی، خروجی (jy, jm, jd)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            - 80 + gd + g_d_m[gm - 1])
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def today_jalali() -> str:
    """تاریخ امروز به‌صورت رشته شمسی «YYYY/MM/DD» (صفرپرشده)."""
    jy, jm, jd = gregorian_to_jalali(date.today().year, date.today().month, date.today().day)
    return f"{jy}/{jm:02d}/{jd:02d}"


def parse_jalali(s: str):
    """
    رشته تاریخ شمسی را به تاپل (سال، ماه، روز) تبدیل می‌کند.
    جداکننده / یا -؛ در صورت نامعتبر بودن None.
    """
    if not s:
        return None
    s = s.strip().replace("-", "/")
    parts = s.split("/")
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None


def is_past_due(due_date: str, today: str = None) -> bool:
    """آیا سررسید (شمسی) از امروز گذشته است؟ مقایسه امن بدون توجه به صفرپرشدن."""
    d = parse_jalali(due_date)
    t = parse_jalali(today or today_jalali())
    if not d or not t:
        return False
    return d < t
