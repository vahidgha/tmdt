"""API ماژول گزارش‌ها"""
from flask import Blueprint, jsonify, request
from flask_login import login_required
from sqlalchemy.orm import selectinload

from ... import db_session
from ...models import Booklet, Payment, TransferHistory, User
from ...utils.export import export_pdf, export_xlsx
from ...utils.http import require_admin

bp = Blueprint("reports", __name__)

_STATUS_LBL = {"paid": "پرداخت‌شده", "unpaid": "در انتظار", "overdue": "معوق"}


@bp.get("/reports")
@login_required
def reports():
    err = require_admin()
    if err: return err

    rtype = request.args.get("type", "finance")

    if rtype == "members":
        return _members_report()
    if rtype == "booklets":
        return _booklets_report()

    return _finance_report()


def _members_report():
    # eager-load دفترچه‌ها (+ پروژه/مالک هرکدام) و پرداخت‌ها در کوئری‌های
    # batched — قبلاً برای هر عضو، جداگانه دفترچه و پرداخت لود می‌شد (N+1)
    members = (db_session.query(User).filter_by(role="member")
               .options(selectinload(User.booklets).selectinload(Booklet.project),
                        selectinload(User.booklets).selectinload(Booklet.owner),
                        selectinload(User.payments))
               .order_by(User.last_name).all())
    result  = []
    for m in members:
        d              = m.to_dict()
        d["booklets"]  = [b.to_dict() for b in m.booklets]
        d["total_debt"] = sum(
            p.amount for p in m.payments if p.status in ("unpaid", "overdue")
        )
        result.append(d)
    return jsonify(members=result)


def _booklets_report():
    from sqlalchemy import func

    booklets = (db_session.query(Booklet).filter(Booklet.deleted_at.is_(None))
               .options(selectinload(Booklet.project), selectinload(Booklet.owner),
                        selectinload(Booklet.payments))
               .order_by(Booklet.project_id, Booklet.serial).all())
    transfer_counts = dict(
        db_session.query(TransferHistory.booklet_id, func.count(TransferHistory.id))
        .group_by(TransferHistory.booklet_id).all()
    )

    result = []
    for b in booklets:
        d = b.to_dict()
        d["debt"] = sum(p.amount for p in b.payments if p.status in ("unpaid", "overdue"))
        d["transfer_count"] = transfer_counts.get(b.id, 0)
        result.append(d)
    return jsonify(booklets=result)


def _finance_report():
    payments = db_session.query(Payment).order_by(Payment.due_date).all()
    return jsonify(payments=[{
        "id": p.id, "amount": p.amount,
        "due_date": p.due_date, "paid_date": p.paid_date,
        "status": p.status, "description": p.description,
        "user":    {"full_name": p.user.full_name} if p.user else None,
        "booklet": {
            "code": p.booklet.code,
            "project_name": p.booklet.project.name if p.booklet and p.booklet.project else "",
        } if p.booklet else None,
    } for p in payments])


# ── خروجی اکسل/PDF — همان فیلترهای صفحه گزارش‌ساز، سمت سرور دوباره اعمال می‌شود ──

def _subtitle_from_filters(project_name=None, status=None, date_from=None, date_to=None, name=None, share_type=None):
    parts = []
    if project_name: parts.append(f"پروژه: {project_name}")
    if status:        parts.append(f"وضعیت: {_STATUS_LBL.get(status, status)}")
    if share_type:    parts.append(f"نوع سهم: {'تمام‌سهم' if share_type == 'full' else 'نیم‌سهم'}")
    if date_from or date_to: parts.append(f"بازه: {date_from or '—'} تا {date_to or '—'}")
    if name:          parts.append(f"جستجو: {name}")
    return " — ".join(parts)


def _finance_export_rows():
    project_id = request.args.get("project_id")
    status     = request.args.get("status", "").strip()
    name       = request.args.get("name", "").strip()

    q = db_session.query(Payment).options(
        selectinload(Payment.user), selectinload(Payment.booklet).selectinload(Booklet.project))
    if status:
        q = q.filter(Payment.status == status)
    if project_id:
        q = q.join(Booklet, Payment.booklet_id == Booklet.id).filter(Booklet.project_id == int(project_id))
    payments = q.order_by(Payment.due_date).all()
    if name:
        payments = [p for p in payments if p.user and name in p.user.full_name]

    headers = ["عضو", "پروژه", "دفترچه", "مبلغ (ریال)", "سررسید", "وضعیت"]
    rows = [[
        p.user.full_name if p.user else "—",
        p.booklet.project.name if p.booklet and p.booklet.project else "—",
        p.booklet.code if p.booklet else "—",
        p.amount,
        p.due_date,
        _STATUS_LBL.get(p.status, p.status),
    ] for p in payments]

    proj_name = None
    if project_id:
        from ...models import Project
        proj = db_session.get(Project, int(project_id))
        proj_name = proj.name if proj else None
    subtitle = _subtitle_from_filters(project_name=proj_name, status=status, name=name)
    return headers, rows, subtitle


def _members_export_rows():
    project_id = request.args.get("project_id")
    name       = request.args.get("name", "").strip()

    members = (db_session.query(User).filter_by(role="member")
               .options(selectinload(User.booklets).selectinload(Booklet.project),
                        selectinload(User.payments))
               .order_by(User.last_name).all())
    if project_id:
        members = [m for m in members if any(str(b.project_id) == project_id for b in m.booklets)]
    if name:
        members = [m for m in members if name in m.full_name]

    headers = ["نام", "نام خانوادگی", "کد ملی", "جنسیت", "موبایل", "دفترچه‌ها", "بدهی (ریال)"]
    rows = []
    for m in members:
        debt = sum(p.amount for p in m.payments if p.status in ("unpaid", "overdue"))
        booklets = " | ".join(
            f"{(b.booklet_number or b.code)} ({b.project.name if b.project else ''})" for b in m.booklets
        ) or "—"
        rows.append([m.first_name or "", m.last_name or "", m.national_code or "—",
                     m.gender or "—", m.phone or "—", booklets, debt])

    proj_name = None
    if project_id:
        from ...models import Project
        proj = db_session.get(Project, int(project_id))
        proj_name = proj.name if proj else None
    subtitle = _subtitle_from_filters(project_name=proj_name, name=name)
    return headers, rows, subtitle


def _booklets_export_rows():
    from sqlalchemy import func

    project_id = request.args.get("project_id")
    share_type = request.args.get("share_type", "").strip()
    name       = request.args.get("name", "").strip()

    q = (db_session.query(Booklet).filter(Booklet.deleted_at.is_(None))
         .options(selectinload(Booklet.project), selectinload(Booklet.owner),
                  selectinload(Booklet.payments)))
    if project_id:
        q = q.filter(Booklet.project_id == int(project_id))
    if share_type:
        q = q.filter(Booklet.share_type == share_type)
    booklets = q.order_by(Booklet.project_id, Booklet.serial).all()
    if name:
        booklets = [b for b in booklets if (b.owner and name in b.owner.full_name) or name in (b.code or "")]

    transfer_counts = dict(
        db_session.query(TransferHistory.booklet_id, func.count(TransferHistory.id))
        .group_by(TransferHistory.booklet_id).all()
    )

    headers = ["کد دفترچه", "شماره دفترچه", "پروژه", "نوع سهم", "مالک فعلی", "شماره قرارداد",
               "تاریخ قرارداد", "مبلغ قرارداد (ریال)", "بدهی باقی‌مانده (ریال)", "تعداد انتقال"]
    rows = [[
        b.code,
        b.booklet_number or "—",
        b.project.name if b.project else "—",
        "تمام‌سهم" if b.share_type == "full" else "نیم‌سهم",
        b.owner.full_name if b.owner else "—",
        b.contract_no or "—",
        b.contract_date or "—",
        b.contract_amount or 0,
        sum(p.amount for p in b.payments if p.status in ("unpaid", "overdue")),
        transfer_counts.get(b.id, 0),
    ] for b in booklets]

    proj_name = None
    if project_id:
        from ...models import Project
        proj = db_session.get(Project, int(project_id))
        proj_name = proj.name if proj else None
    subtitle = _subtitle_from_filters(project_name=proj_name, share_type=share_type, name=name)
    return headers, rows, subtitle


def _history_export_rows():
    from sqlalchemy import or_
    project_id = request.args.get("project_id")
    name       = request.args.get("name", "").strip()
    date_from  = request.args.get("date_from", "").strip()
    date_to    = request.args.get("date_to", "").strip()

    q = (db_session.query(TransferHistory)
         .join(Booklet, TransferHistory.booklet_id == Booklet.id)
         .options(selectinload(TransferHistory.booklet).selectinload(Booklet.project),
                  selectinload(TransferHistory.from_user), selectinload(TransferHistory.to_user)))
    if project_id:
        q = q.filter(Booklet.project_id == int(project_id))
    if name:
        q = q.join(User, TransferHistory.to_user_id == User.id).filter(
            or_(User.first_name.contains(name), User.last_name.contains(name)))
    if date_from:
        q = q.filter(TransferHistory.date >= date_from)
    if date_to:
        q = q.filter(TransferHistory.date <= date_to + " 23:59:59")
    items = q.order_by(TransferHistory.date.desc()).all()

    headers = ["تاریخ", "دفترچه", "پروژه", "از", "به"]
    rows = [[
        h.date.strftime("%Y/%m/%d") if h.date else "—",
        h.booklet.code if h.booklet else "—",
        h.booklet.project.name if h.booklet and h.booklet.project else "—",
        h.from_user.full_name if h.from_user else "—",
        h.to_user.full_name if h.to_user else "—",
    ] for h in items]

    proj_name = None
    if project_id:
        from ...models import Project
        proj = db_session.get(Project, int(project_id))
        proj_name = proj.name if proj else None
    subtitle = _subtitle_from_filters(project_name=proj_name, date_from=date_from, date_to=date_to, name=name)
    return headers, rows, subtitle


_REPORT_BUILDERS = {
    "finance":  ("گزارش مالی و اقساط", _finance_export_rows),
    "members":  ("گزارش اعضا", _members_export_rows),
    "booklets": ("گزارش دفترچه‌محور", _booklets_export_rows),
    "history":  ("گزارش تاریخچه انتقال", _history_export_rows),
}


@bp.get("/reports/export")
@login_required
def reports_export():
    err = require_admin()
    if err: return err

    rtype = request.args.get("type", "finance")
    fmt   = request.args.get("format", "xlsx")
    if rtype not in _REPORT_BUILDERS:
        return jsonify(error="نوع گزارش نامعتبر است."), 400

    title, builder = _REPORT_BUILDERS[rtype]
    headers, rows, subtitle = builder()
    filename_base = f"{rtype}_report"

    if fmt == "pdf":
        return export_pdf(headers, rows, title, f"{filename_base}.pdf", subtitle=subtitle)
    return export_xlsx(headers, rows, title, f"{filename_base}.xlsx", subtitle=subtitle)
