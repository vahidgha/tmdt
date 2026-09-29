#!/usr/bin/env python3
"""
اسناد هزینه‌ی وارد‌شده از شیت «پرداختی» (پرداخت‌های پیمانکار) که هنوز به هیچ
پروژه‌ای لینک نشده‌اند را به پروژه مشخص‌شده وصل می‌کند.

اجرا:
    env/bin/python scripts/link_expenses_to_project.py --project-name "شهر سنگ"

ایمن برای اجرای چندباره — فقط رکوردهایی که project_id ندارند را به‌روزرسانی می‌کند.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_pkg
from app import create_app
from app.models import ExpenseVoucher, Project

db_session = None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-name", default="شهر سنگ")
    args = ap.parse_args()

    global db_session
    app = create_app()
    db_session = app_pkg.db_session

    with app.app_context():
        project = db_session.query(Project).filter_by(name=args.project_name).first()
        if not project:
            raise SystemExit(f"پروژه «{args.project_name}» پیدا نشد — اول اسکریپت create_booklets_for_members.py را اجرا کنید.")

        rows = (db_session.query(ExpenseVoucher)
                .filter(ExpenseVoucher.category == "contractor",
                        ExpenseVoucher.project_id.is_(None))
                .all())
        for r in rows:
            r.project_id = project.id
        db_session.commit()
        print(f"{len(rows)} سند هزینه به پروژه «{project.name}» (id={project.id}) لینک شد.")


if __name__ == "__main__":
    main()
