#!/usr/bin/env python3
"""
علامت‌گذاری اقساط معوق + یادآوری خودکار.

هر قسط unpaid که سررسیدش (شمسی) گذشته باشد → overdue می‌شود
و برای عضو یادآوری پیامک (sms.ir) و در صورت اتصال، پیام بله ارسال می‌گردد.

اجرای روزانه با cron (مثلاً ۸ صبح):
  0 8 * * * cd /home/admin/tmdz-app && env/bin/python scripts/mark_overdue.py >> /var/log/tmdz-overdue.log 2>&1

اجرای بدون ارسال یادآوری (فقط علامت‌گذاری):
  python scripts/mark_overdue.py --no-remind
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db_session          # noqa: E402
from app.models import Payment, User             # noqa: E402
from app.utils.jalali import is_past_due, today_jalali  # noqa: E402
from app import sms, bot                          # noqa: E402


def run(remind: bool = True):
    app = create_app()
    with app.app_context():
        today = today_jalali()
        newly_overdue = []

        unpaid = db_session.query(Payment).filter(Payment.status == "unpaid").all()
        for p in unpaid:
            if is_past_due(p.due_date, today):
                p.status = "overdue"
                newly_overdue.append(p)
        db_session.commit()
        print(f"[{today}] {len(newly_overdue)} قسط به معوق تغییر یافت.")

        if not remind:
            return

        # یادآوری به‌ازای هر عضو (یک پیام جمع‌بندی)
        by_user = {}
        for p in newly_overdue:
            by_user.setdefault(p.user_id, []).append(p)

        sent = 0
        for uid, items in by_user.items():
            user = db_session.get(User, uid)
            if not user:
                continue
            total = sum(x.amount for x in items)
            text = (f"عضو گرامی {user.full_name}،\n"
                    f"{len(items)} قسط به مبلغ کل {total:,} ریال سررسید گذشته دارید. "
                    f"لطفاً نسبت به پرداخت اقدام فرمایید.")
            ok = False
            if user.phone:
                ok = sms.send_message(user.phone, text, db_session)
            if user.bale_chat_id:
                bot.send(user.bale_chat_id, "🔔 *یادآوری قسط معوق*\n\n" + text, db_session)
                ok = True
            if ok:
                sent += 1
        print(f"یادآوری برای {sent} عضو ارسال شد.")


if __name__ == "__main__":
    run(remind="--no-remind" not in sys.argv)
