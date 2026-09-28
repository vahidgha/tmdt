#!/usr/bin/env python3
"""
برای هر عضوی که هنوز دفترچه (واحد مالکیت) در پروژه مشخص‌شده ندارد، یک دفترچه
می‌سازد — کد دفترچه = کدپرسنلی عضو، مبلغ قرارداد = جمع واریزی‌های فعال همان عضو.

اجرا:
    env/bin/python scripts/create_booklets_for_members.py --project-name "شهر سنگ"

ایمن برای اجرای چندباره است — عضوی که از قبل دفترچه در این پروژه دارد رد می‌شود.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func

import app as app_pkg
from app import create_app
from app.models import Booklet, DepositVoucher, Project, User

db_session = None


def get_or_create_project(name, location, status):
    proj = db_session.query(Project).filter_by(name=name).first()
    if proj:
        return proj
    proj = Project(name=name, location=location, status=status, active=True)
    db_session.add(proj)
    db_session.commit()
    return proj


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-name", default="شهر سنگ")
    ap.add_argument("--location", default="")
    ap.add_argument("--status", default="active", choices=["active", "completed", "upcoming"])
    ap.add_argument("--share-type", default="full", choices=["full", "half"])
    args = ap.parse_args()

    global db_session
    app = create_app()
    db_session = app_pkg.db_session

    with app.app_context():
        project = get_or_create_project(args.project_name, args.location, args.status)
        print(f"پروژه: {project.name} (id={project.id})")

        existing_owner_ids = {
            b.owner_id for b in db_session.query(Booklet)
            .filter_by(project_id=project.id, deleted_at=None).all()
        }
        last_serial = db_session.query(func.max(Booklet.serial)).filter_by(
            project_id=project.id).scalar() or 0

        deposit_sums = dict(
            db_session.query(DepositVoucher.user_id, func.coalesce(func.sum(DepositVoucher.amount), 0))
            .filter(DepositVoucher.status == "active", DepositVoucher.user_id.isnot(None))
            .group_by(DepositVoucher.user_id).all()
        )

        created = skipped_has_booklet = skipped_no_deposit = 0
        members = db_session.query(User).filter_by(role="member").order_by(User.id).all()

        for m in members:
            if m.id in existing_owner_ids:
                skipped_has_booklet += 1
                continue
            total = int(deposit_sums.get(m.id, 0))
            if total <= 0:
                skipped_no_deposit += 1
                continue

            code = (m.personnel_code or m.national_code or f"U{m.id}")[:30]
            dup = db_session.query(Booklet).filter_by(project_id=project.id, code=code).first()
            if dup:
                code = f"{code}-{m.id}"[:30]

            last_serial += 1
            db_session.add(Booklet(
                code=code,
                serial=last_serial,
                project_id=project.id,
                owner_id=m.id,
                share_type=args.share_type,
                contract_amount=total,
            ))
            created += 1

        db_session.commit()

        project.total_booklets = db_session.query(func.count(Booklet.id)).filter_by(
            project_id=project.id, deleted_at=None).scalar()
        db_session.commit()

        print(f"دفترچه جدید: {created}")
        print(f"رد شد (از قبل دفترچه داشت): {skipped_has_booklet}")
        print(f"رد شد (واریزی فعالی نداشت): {skipped_no_deposit}")
        print(f"کل دفترچه‌های پروژه: {project.total_booklets}")


if __name__ == "__main__":
    main()
