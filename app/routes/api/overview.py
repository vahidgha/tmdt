"""API نمای کلی داشبورد مدیر — آمار خلاصه یک‌نگاهی"""
from datetime import datetime

from flask import Blueprint, jsonify
from flask_login import login_required
from sqlalchemy import func

from ... import db_session
from ...models import (Booklet, DepositVoucher, ExpenseVoucher, Form, Payment, Project,
                       Ticket, TransferRequest, User, VoucherAllocation)
from ...utils.http import require_admin
from ...utils.jalali import today_jalali

bp = Blueprint("overview", __name__)


@bp.get("/overview")
@login_required
def admin_overview():
    """آمار کلی برای داشبورد مدیر."""
    err = require_admin()
    if err: return err

    today = today_jalali()
    month_prefix = today.rsplit("/", 1)[0] + "/"   # مثال: "1404/05/"

    # اعضا
    members_total  = db_session.query(func.count(User.id)).filter_by(role="member").scalar()
    members_active = db_session.query(func.count(User.id)).filter_by(role="member", active=True).scalar()

    # پروژه‌ها و دفترچه‌ها
    projects_active = db_session.query(func.count(Project.id)).filter_by(active=True).scalar()
    booklets_total  = db_session.query(func.count(Booklet.id)).filter(Booklet.deleted_at.is_(None)).scalar()

    # وصولی این ماه (تخصیص‌های اسناد فعالِ همین ماه شمسی)
    month_collected = int(db_session.query(func.coalesce(func.sum(VoucherAllocation.amount), 0))
                          .join(DepositVoucher, VoucherAllocation.voucher_id == DepositVoucher.id)
                          .filter(DepositVoucher.status == "active",
                                  DepositVoucher.deposit_date.like(month_prefix + "%")).scalar())
    month_deposited = int(db_session.query(func.coalesce(func.sum(DepositVoucher.amount), 0))
                          .filter(DepositVoucher.status == "active",
                                  DepositVoucher.deposit_date.like(month_prefix + "%")).scalar())

    # معوقات
    overdue_q      = db_session.query(Payment).filter(Payment.status == "overdue")
    overdue_count  = overdue_q.count()
    overdue_amount = int(overdue_q.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar())

    # کارهای در انتظار
    pending_transfers = db_session.query(func.count(TransferRequest.id)).filter(
        TransferRequest.status.in_(("pending", "awaiting_docs"))).scalar()
    open_tickets = db_session.query(func.count(Ticket.id)).filter(
        Ticket.status.in_(("open", "in_progress", "waiting"))).scalar()

    # تراز کل
    total_deposited = int(db_session.query(func.coalesce(func.sum(DepositVoucher.amount), 0))
                          .filter_by(status="active").scalar())
    total_expenses  = int(db_session.query(func.coalesce(func.sum(ExpenseVoucher.amount), 0))
                          .filter_by(status="active").scalar())

    # آخرین تیکت‌ها، درخواست‌های نقل و انتقال، و فرم‌ها — برای باکس‌های «اخیر» داشبورد
    recent_tickets = db_session.query(Ticket).order_by(Ticket.updated_at.desc()).limit(5).all()
    recent_transfers = db_session.query(TransferRequest).order_by(
        TransferRequest.created_at.desc()).limit(5).all()
    recent_forms = db_session.query(Form).order_by(Form.updated_at.desc()).limit(5).all()

    return jsonify(
        recent_tickets=[{
            "id": t.id, "number": t.number, "subject": t.subject,
            "status": t.status, "priority": t.priority,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        } for t in recent_tickets],
        recent_transfers=[{
            "id": r.id, "new_owner_full_name": r.new_owner_full_name,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in recent_transfers],
        recent_forms=[{
            "id": f.id, "title": f.title, "status": f.status,
            "submission_count": len(f.submissions),
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        } for f in recent_forms],
        members={"total": members_total, "active": members_active},
        projects={"active": projects_active, "booklets": booklets_total},
        this_month={"collected": month_collected, "deposited": month_deposited, "label": month_prefix.rstrip("/")},
        overdue={"count": overdue_count, "amount": overdue_amount},
        pending={"transfers": pending_transfers, "tickets": open_tickets},
        balance={"deposited": total_deposited, "expenses": total_expenses,
                 "net": total_deposited - total_expenses},
    )
