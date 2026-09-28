"""API ماژول تیکت‌های پشتیبانی"""
import math
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from ... import bot, db_session
from ...models import MarketplaceListing, Ticket, TicketMessage
from ...utils.http import get_request_body, log_activity, require_admin

bp = Blueprint("tickets", __name__)

VALID_STATUSES = ("open", "in_progress", "waiting", "resolved", "closed")


def _can_access_ticket(t: Ticket) -> bool:
    """
    دسترسی معمول: ادمین یا سازندهٔ تیکت. علاوه بر آن، تیکت‌هایی که از یک
    درخواست خرید در بازار نقل‌وانتقال ساخته شده‌اند (listing_id) برای
    فروشندهٔ همان آگهی هم قابل مشاهده/پاسخ هستند — چون سازندهٔ این تیکت‌ها
    ممکن است اصلاً کاربر لاگین‌کرده نباشد (خریدار مهمان).
    """
    if current_user.role == "admin" or t.creator_id == current_user.id:
        return True
    if t.listing_id:
        listing = db_session.get(MarketplaceListing, t.listing_id)
        return bool(listing and listing.seller_id == current_user.id)
    return False


@bp.get("/tickets")
@login_required
def tickets_list():
    status   = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()
    category = request.args.get("category", "").strip()
    search   = request.args.get("search", "").strip()
    page     = int(request.args.get("page", 1))
    per_page = 20

    q = (db_session.query(Ticket)
         .options(selectinload(Ticket.creator), selectinload(Ticket.assigned),
                  selectinload(Ticket.messages))
         .order_by(Ticket.updated_at.desc()))
    if current_user.role != "admin":
        my_listing_ids = [row[0] for row in db_session.query(MarketplaceListing.id)
                          .filter(MarketplaceListing.seller_id == current_user.id).all()]
        q = q.filter(or_(Ticket.creator_id == current_user.id, Ticket.listing_id.in_(my_listing_ids)))
    if status:   q = q.filter(Ticket.status == status)
    if priority: q = q.filter(Ticket.priority == priority)
    if category: q = q.filter(Ticket.category == category)
    if search:   q = q.filter(or_(Ticket.subject.contains(search)))

    total   = q.count()
    tickets = q.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify(
        tickets=[t.to_dict() for t in tickets],
        total=total,
        page=page,
        pages=math.ceil(total / per_page) or 1,
    )


@bp.post("/tickets")
@login_required
def ticket_create():
    data    = get_request_body()
    subject = (data.get("subject") or "").strip()
    body    = (data.get("body")    or "").strip()
    if not subject or not body:
        return jsonify(error="موضوع و متن پیام الزامی است."), 400

    last_num = db_session.query(func.max(Ticket.number)).scalar() or 1000
    t = Ticket(
        number=last_num + 1,
        subject=subject,
        category=data.get("category", "general"),
        priority=data.get("priority", "normal"),
        creator_id=current_user.id,
    )
    db_session.add(t)
    db_session.flush()
    db_session.add(TicketMessage(ticket_id=t.id, sender_id=current_user.id,
                                 body=body, is_admin=False))
    log_activity("ticket_create", f"تیکت #{t.number}: {subject}", "ticket")
    db_session.commit()

    bot.notify_admins(
        f"🎫 *تیکت جدید #{t.number}*\n\n"
        f"👤 از: {current_user.full_name}\n"
        f"📌 موضوع: {subject}\n\n"
        f"برای بررسی وارد پنل شوید.",
        db_session,
    )
    return jsonify(ok=True, ticket=t.to_dict()), 201


@bp.get("/tickets/<int:tid>")
@login_required
def ticket_get(tid):
    t = db_session.get(Ticket, tid)
    if not t:
        return jsonify(error="یافت نشد."), 404
    if not _can_access_ticket(t):
        return jsonify(error="دسترسی ندارید."), 403

    d = t.to_dict(with_messages=True)
    return jsonify(ticket=d, messages=d.get("messages", []))


@bp.post("/tickets/<int:tid>/reply")
@bp.post("/tickets/<int:tid>/messages")
@login_required
def ticket_reply(tid):
    t = db_session.get(Ticket, tid)
    if not t:
        return jsonify(error="یافت نشد."), 404
    if not _can_access_ticket(t):
        return jsonify(error="دسترسی ندارید."), 403
    if t.status == "closed":
        return jsonify(error="تیکت بسته است."), 400

    data     = get_request_body()
    body     = (data.get("body") or "").strip()
    if not body:
        return jsonify(error="متن پیام الزامی است."), 400

    is_admin = current_user.role == "admin"
    msg      = TicketMessage(ticket_id=tid, sender_id=current_user.id, body=body, is_admin=is_admin)
    db_session.add(msg)

    _update_ticket_status_on_reply(t, is_admin, data)
    log_activity("ticket_reply", f"تیکت #{t.number}", "ticket")
    db_session.commit()

    if is_admin:
        bot.notify_user(t.creator, f"💬 *پاسخ جدید به تیکت #{t.number}*\n\n{body[:200]}", db_session)
    else:
        bot.notify_admins(f"💬 *پیام جدید در تیکت #{t.number}*\n👤 {current_user.full_name}\n\n{body[:200]}", db_session)

    return jsonify(ok=True, message=msg.to_dict(), ticket_status=t.status)


@bp.post("/tickets/<int:tid>/status")
@login_required
def ticket_set_status(tid):
    err = require_admin()
    if err: return err

    t = db_session.get(Ticket, tid)
    if not t:
        return jsonify(error="یافت نشد."), 404

    new_status = get_request_body().get("status", "")
    if new_status not in VALID_STATUSES:
        return jsonify(error="وضعیت نامعتبر."), 400

    t.status     = new_status
    t.updated_at = datetime.utcnow()
    if new_status == "closed":
        t.closed_at = datetime.utcnow()

    log_activity("ticket_status", f"تیکت #{t.number} → {new_status}", "ticket")
    db_session.commit()
    return jsonify(ok=True)


@bp.delete("/tickets/<int:tid>")
@login_required
def ticket_delete(tid):
    err = require_admin()
    if err: return err

    t = db_session.get(Ticket, tid)
    if not t:
        return jsonify(error="یافت نشد."), 404

    db_session.delete(t)
    db_session.commit()
    return jsonify(ok=True)


def _update_ticket_status_on_reply(ticket: Ticket, is_admin: bool, data: dict) -> None:
    """وضعیت تیکت را بر اساس پاسخ‌دهنده و درخواست به‌روزرسانی می‌کند."""
    ticket.updated_at = datetime.utcnow()

    if is_admin:
        if ticket.status == "open":
            ticket.status = "in_progress"
        new_status = data.get("status")
        if new_status and new_status in VALID_STATUSES:
            ticket.status = new_status
            if new_status == "closed":
                ticket.closed_at = datetime.utcnow()
    elif ticket.status in ("in_progress", "waiting"):
        ticket.status = "open"
