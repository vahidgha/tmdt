"""API ماژول مالی — طرح‌های پرداخت، اقساط و گزارش مالی"""
import math
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ... import db_session
from ...models import Booklet, Notification, Payment, PaymentPlan
from ...utils.files import FileValidationError, save_document
from ...utils.http import get_request_body, log_activity, require_admin

bp = Blueprint("finance", __name__)


# ── Payment Plans ─────────────────────────────────────────────────────────────

@bp.get("/finance/plans")
@bp.get("/plans")
@login_required
def plans_list():
    project_id = request.args.get("project_id")
    q = db_session.query(PaymentPlan)
    if project_id:
        q = q.filter_by(project_id=int(project_id))
    plans = q.order_by(PaymentPlan.created_at.desc()).all()
    return jsonify(plans=[
        {
            "id": p.id, "title": p.title,
            "total_amount": p.total_amount, "installments": p.installments,
            "start_date": p.start_date, "description": p.description,
            "project_id": p.project_id,
            "project_name": p.project.name if p.project else "",
        }
        for p in plans
    ])


@bp.post("/finance/plans")
@bp.post("/plans")
@login_required
def plans_create():
    err = require_admin()
    if err: return err

    data = get_request_body()
    required = ("title", "total_amount", "installments", "start_date")
    if not all(data.get(k) for k in required):
        return jsonify(error="عنوان، مبلغ کل، تعداد اقساط و تاریخ شروع الزامی هستند."), 400

    plan = PaymentPlan(
        project_id=int(data["project_id"]) if data.get("project_id") else None,
        title=data["title"],
        total_amount=int(data["total_amount"]),
        installments=int(data["installments"]),
        start_date=data["start_date"],
        description=data.get("description"),
    )
    db_session.add(plan)
    db_session.flush()

    # اعتبارسنجی فرمت تاریخ
    sep   = "/" if "/" in plan.start_date else "-"
    parts = plan.start_date.split(sep)
    if len(parts) < 3:
        db_session.rollback()
        return jsonify(error="فرمت تاریخ شروع نامعتبر است. مثال: ۱۴۰۴/۰۱/۰۱"), 400

    sy, sm, sd = int(parts[0]), int(parts[1]), parts[2]
    count = _generate_payment_installments(plan, sy, sm, sd)

    db_session.commit()
    log_activity("plan_create", f"طرح پرداخت: {plan.title} — {count} قسط ایجاد شد", "finance")
    return jsonify(ok=True, plan_id=plan.id, payments_created=count), 201


# ── Payments ──────────────────────────────────────────────────────────────────

@bp.get("/finance/payments")
@bp.get("/payments")
@login_required
def payments_list():
    """
    لیست پرداخت‌ها — با فیلتر و صفحه‌بندی اختیاری سمت سرور.
    پارامترها: status، search (نام عضو)، page، per_page.
    بدون page همه برگردانده می‌شود (سازگاری قبلی).
    """
    import math
    from sqlalchemy import or_
    from ...models import User

    q = db_session.query(Payment)
    if current_user.role == "member":
        q = q.filter_by(user_id=current_user.id)

    status = (request.args.get("status") or "").strip()
    search = (request.args.get("search") or "").strip()
    page   = request.args.get("page", type=int)
    per_page = min(request.args.get("per_page", 50, type=int) or 50, 200)

    if status:
        q = q.filter(Payment.status == status)
    if search:
        like = f"%{search}%"
        q = q.join(User, Payment.user_id == User.id).filter(or_(
            User.first_name.ilike(like), User.last_name.ilike(like),
            User.national_code.ilike(like),
        ))

    q     = q.order_by(Payment.due_date)
    total = q.count()
    if page:
        items = q.offset((page - 1) * per_page).limit(per_page).all()
        pages = math.ceil(total / per_page) or 1
    else:
        items = q.all()
        pages = 1

    return jsonify(payments=[_payment_dict(p) for p in items],
                   total=total, page=page or 1, pages=pages)


@bp.patch("/finance/payments/<int:pid>")
@login_required
def payments_update(pid):
    err = require_admin()
    if err: return err

    p = db_session.get(Payment, pid)
    if not p:
        return jsonify(error="یافت نشد."), 404

    data = get_request_body()
    if "status" in data:
        p.status = data["status"]
    if "paid_date" in data:
        p.paid_date = data["paid_date"]

    if p.status == "paid":
        db_session.add(Notification(
            user_id=p.user_id,
            title="تأیید پرداخت",
            body=f"پرداخت {p.amount:,} ریال تأیید شد.",
            type="success",
        ))
        log_activity("payment_confirm", f"تأیید پرداخت {p.amount:,} ریال — کاربر {p.user_id}", "finance")

    db_session.commit()
    return jsonify(ok=True)


@bp.post("/finance/payments/<int:pid>/upload")
@login_required
def payments_upload(pid):
    """آپلود فیش پرداخت توسط عضو"""
    p = db_session.get(Payment, pid)
    if not p:
        return jsonify(error="یافت نشد."), 404
    if current_user.role == "member" and p.user_id != current_user.id:
        return jsonify(error="دسترسی ندارید."), 403

    f = request.files.get("receipt")
    if not f:
        return jsonify(error="فایل ارسال نشده."), 400

    try:
        p.receipt_path = save_document(f, "payments")
    except FileValidationError as e:
        return jsonify(error=str(e)), 400

    db_session.commit()
    return jsonify(ok=True, receipt_path=p.receipt_path)


@bp.get("/finance/summary")
@login_required
def finance_summary():
    q = db_session.query(Payment)
    if current_user.role == "member":
        q = q.filter_by(user_id=current_user.id)
    all_payments = q.all()

    def _group(status):
        items = [p for p in all_payments if p.status == status]
        return {"amount": sum(x.amount for x in items), "count": len(items)}

    paid    = _group("paid")
    unpaid  = _group("unpaid")
    overdue = _group("overdue")
    return jsonify(
        summary={
            "total":   {"amount": sum(p.amount for p in all_payments), "count": len(all_payments)},
            "paid":    paid,
            "unpaid":  unpaid,
            "overdue": overdue,
        },
        total_paid=paid["amount"],
        total_unpaid=unpaid["amount"],
        total_overdue=overdue["amount"],
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _generate_payment_installments(plan: PaymentPlan, sy: int, sm: int, sd: str) -> int:
    """
    برای هر دفترچه مرتبط با طرح، اقساط ماهانه ایجاد می‌کند.
    نیم‌سهم نصف مبلغ می‌پردازد.
    تعداد کل اقساط ایجادشده را برمی‌گرداند.
    """
    q = db_session.query(Booklet).filter(Booklet.deleted_at.is_(None))
    if plan.project_id:
        q = q.filter_by(project_id=plan.project_id)
    booklets = q.all()

    per        = math.ceil(plan.total_amount / plan.installments)
    count      = 0
    seen_users = set()

    for b in booklets:
        amt = per if b.share_type == "full" else per // 2
        for i in range(plan.installments):
            month, year = sm + i, sy
            while month > 12:
                month -= 12
                year  += 1
            db_session.add(Payment(
                user_id=b.owner_id,
                booklet_id=b.id,
                plan_id=plan.id,
                amount=amt,
                due_date=f"{year}/{str(month).zfill(2)}/{sd}",
                description=f"{plan.title} — قسط {i + 1} از {plan.installments}",
            ))
            count += 1

        if b.owner_id not in seen_users:
            project_name = plan.project.name if plan.project else ""
            db_session.add(Notification(
                user_id=b.owner_id,
                title="طرح پرداخت جدید",
                body=f"طرح «{plan.title}» برای پروژه «{project_name}» تعریف شد.",
                type="info",
            ))
            seen_users.add(b.owner_id)

    return count


def _payment_dict(p: Payment) -> dict:
    return {
        "id": p.id, "amount": p.amount,
        "due_date": p.due_date, "paid_date": p.paid_date,
        "status": p.status, "description": p.description,
        "receipt_path": p.receipt_path,
        "user":    {"id": p.user.id, "full_name": p.user.full_name} if p.user else None,
        "plan":    {"id": p.plan.id, "title": p.plan.title} if p.plan else None,
        "booklet": {
            "code": p.booklet.code,
            "share_type": p.booklet.share_type,
            "project_name": p.booklet.project.name if p.booklet and p.booklet.project else "",
        } if p.booklet else None,
    }
