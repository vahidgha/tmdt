"""API ماژول نقل و انتقال دفترچه"""
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from werkzeug.security import generate_password_hash

from ... import bot, db_session
from ...constants import DEFAULT_NEW_OWNER_PASSWORD
from ...models import (Booklet, Notification, TransferHistory,
                       TransferRequest, User)
from ...utils.files import FileValidationError, save_document
from ...utils.http import get_request_body, log_activity, require_admin
from ...utils.validation import normalize_digits

bp = Blueprint("transfers", __name__)


@bp.post("/requests/new")
@login_required
def requests_new():
    """ثبت درخواست انتقال توسط عضو (JSON)"""
    data    = get_request_body()
    booklet = db_session.get(Booklet, int(data.get("booklet_id", 0) or 0))
    if not booklet or booklet.deleted_at or booklet.owner_id != current_user.id:
        return jsonify(error="دفترچه یافت نشد یا متعلق به شما نیست."), 403

    pending = db_session.query(TransferRequest).filter_by(
        booklet_id=booklet.id, status="pending"
    ).first()
    if pending:
        return jsonify(error="یک درخواست در انتظار بررسی وجود دارد."), 409

    req = TransferRequest(
        booklet_id=booklet.id,
        requester_id=current_user.id,
        new_owner_first_name=data.get("new_owner_first_name", "").strip(),
        new_owner_last_name=data.get("new_owner_last_name", "").strip(),
        new_owner_national_code=normalize_digits(data.get("new_owner_national_code", "")).strip(),
        new_owner_phone=normalize_digits(data.get("new_owner_phone", "")).strip(),
        note=data.get("note", ""),
    )
    db_session.add(req)
    _notify_admins_new_request(booklet, current_user)
    db_session.commit()
    return jsonify(ok=True, id=req.id), 201


@bp.post("/requests")
@login_required
def requests_create():
    """ثبت درخواست نقل و انتقال با آپلود مدارک (multipart/form-data)"""
    booklet_id = request.form.get("booklet_id") or get_request_body().get("booklet_id")
    if not booklet_id:
        return jsonify(error="دفترچه را انتخاب کنید."), 400

    booklet = db_session.get(Booklet, int(booklet_id))
    if not booklet or booklet.deleted_at or (current_user.role != "admin" and booklet.owner_id != current_user.id):
        return jsonify(error="دفترچه یافت نشد."), 404

    fn  = (request.form.get("new_owner_first_name")    or "").strip()
    ln  = (request.form.get("new_owner_last_name")     or "").strip()
    nat = normalize_digits(request.form.get("new_owner_national_code") or "").strip()
    ph  = normalize_digits(request.form.get("new_owner_phone")         or "").strip()
    if not all([fn, ln, nat, ph]):
        return jsonify(error="همه فیلدهای مالک جدید الزامی است."), 400

    req = TransferRequest(
        booklet_id=booklet.id,
        requester_id=current_user.id,
        new_owner_first_name=fn,
        new_owner_last_name=ln,
        new_owner_national_code=nat,
        new_owner_phone=ph,
        note=request.form.get("note") or "",
    )
    db_session.add(req)
    db_session.flush()

    _upload_transfer_documents(req)

    log_activity("transfer_request", f"دفترچه {booklet.code} → {fn} {ln}", "transfer")
    db_session.commit()

    proj_name = booklet.project.name if booklet.project else ""
    bot.notify_admins(
        f"🔔 *درخواست نقل و انتقال جدید*\n\n"
        f"👤 درخواست‌دهنده: {current_user.full_name}\n"
        f"📋 دفترچه: {booklet.code}\n"
        f"🏗 پروژه: {proj_name}\n"
        f"👥 مالک جدید: {fn} {ln}\n\n"
        f"برای بررسی به پنل مدیریت مراجعه کنید.",
        db_session,
    )
    return jsonify(ok=True, request_id=req.id), 201


@bp.get("/requests")
@login_required
def requests_list():
    """لیست درخواست‌ها با فیلتر status/project و جستجو (مالک جدید، کد ملی، کد دفترچه)."""
    from sqlalchemy import or_
    q = db_session.query(TransferRequest)
    if current_user.role != "admin":
        bids = [b.id for b in current_user.booklets]
        q = q.filter(TransferRequest.booklet_id.in_(bids))

    status     = (request.args.get("status") or "").strip()
    project_id = request.args.get("project_id", type=int)
    search     = (request.args.get("search") or "").strip()

    if status:
        q = q.filter(TransferRequest.status == status)
    if project_id:
        q = q.join(Booklet, TransferRequest.booklet_id == Booklet.id).filter(
            Booklet.project_id == project_id)
    if search:
        s = search.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        like = f"%{s}%"
        q = q.outerjoin(Booklet, TransferRequest.booklet_id == Booklet.id).filter(or_(
            TransferRequest.new_owner_first_name.ilike(like),
            TransferRequest.new_owner_last_name.ilike(like),
            TransferRequest.new_owner_national_code.ilike(like),
            TransferRequest.new_owner_phone.ilike(like),
            Booklet.code.ilike(like),
        ))

    items = q.order_by(TransferRequest.created_at.desc()).all()
    return jsonify(requests=[_transfer_request_dict(r) for r in items],
                   docs_address=_docs_address())


def _docs_address() -> str:
    """آدرس تحویل حضوری مدارک از تنظیمات سایت."""
    from ...models import SiteSetting
    row = db_session.get(SiteSetting, "transfer_docs_address")
    return row.value.strip() if row and row.value else ""


@bp.post("/requests/<int:rid>/approve")
@login_required
def requests_approve(rid):
    """
    تأیید اولیه — درخواست به وضعیت «در انتظار دریافت فیزیکی مدارک» می‌رود.
    انتقال مالکیت هنوز انجام نمی‌شود؛ پس از تحویل حضوری مدارک،
    endpoint /requests/<id>/complete انتقال نهایی را انجام می‌دهد.
    """
    err = require_admin()
    if err: return err

    req = db_session.get(TransferRequest, rid)
    if not req:
        return jsonify(error="درخواست یافت نشد."), 404
    if req.status != "pending":
        return jsonify(error="درخواست قبلاً بررسی شده."), 400

    req.status      = "awaiting_docs"
    req.reviewed_at = datetime.utcnow()
    req.review_note = get_request_body().get("review_note", "")
    log_activity("transfer_initial_approve",
                 f"دفترچه {req.booklet.code} — تأیید اولیه، در انتظار مدارک", "transfer")
    db_session.commit()

    address      = _docs_address()
    address_line = f"\n📍 محل تحویل مدارک:\n{address}\n" if address else "\n"
    bot.notify_user(
        req.requester,
        f"📋 *درخواست نقل و انتقال شما تأیید اولیه شد*\n\n"
        f"دفترچه: {req.booklet.code}\n\n"
        f"برای تکمیل فرایند، لطفاً اصل مدارک را حضوری تحویل دهید.{address_line}\n"
        f"پس از دریافت مدارک، انتقال نهایی انجام و اطلاع‌رسانی می‌شود.",
        db_session,
    )
    return jsonify(ok=True, status="awaiting_docs")


@bp.post("/requests/<int:rid>/complete")
@login_required
def requests_complete(rid):
    """
    تأیید نهایی — پس از دریافت حضوری مدارک.
    انتقال مالکیت همین‌جا انجام می‌شود.
    """
    err = require_admin()
    if err: return err

    req = db_session.get(TransferRequest, rid)
    if not req:
        return jsonify(error="درخواست یافت نشد."), 404
    if req.status != "awaiting_docs":
        return jsonify(error="درخواست در مرحله دریافت مدارک نیست."), 400

    old_owner = req.booklet.owner
    new_user  = _find_or_create_new_owner(req)

    req.booklet.owner_id = new_user.id
    remaining = [b for b in old_owner.booklets if b.id != req.booklet_id]
    if not remaining:
        old_owner.active = False

    req.status      = "approved"
    req.reviewed_at = datetime.utcnow()
    note = get_request_body().get("review_note", "")
    if note:
        req.review_note = note

    db_session.add(TransferHistory(
        booklet_id=req.booklet_id,
        from_user_id=old_owner.id,
        to_user_id=new_user.id,
        request_id=req.id,
    ))
    log_activity("transfer_approve", f"دفترچه {req.booklet.code} → {req.new_owner_full_name}", "transfer")
    db_session.commit()

    bot.notify_user(
        old_owner,
        f"✅ *نقل و انتقال نهایی شد*\n\n"
        f"📋 دفترچه: {req.booklet.code}\n"
        f"👥 منتقل‌شده به: {req.new_owner_full_name}\n\n"
        f"مدارک دریافت و انتقال توسط مدیریت ثبت گردید.",
        db_session,
    )
    return jsonify(ok=True)


@bp.post("/requests/<int:rid>/reject")
@login_required
def requests_reject(rid):
    err = require_admin()
    if err: return err

    req = db_session.get(TransferRequest, rid)
    if not req:
        return jsonify(error="یافت نشد."), 404
    if req.status not in ("pending", "awaiting_docs"):
        return jsonify(error="این درخواست قابل رد نیست."), 400

    data            = get_request_body()
    req.status      = "rejected"
    req.reviewed_at = datetime.utcnow()
    req.review_note = data.get("review_note", "")

    booklet_code = req.booklet.code if req.booklet else "؟"
    log_activity("transfer_reject", f"دفترچه {booklet_code} — {req.review_note}", "transfer")
    db_session.commit()

    note_suffix = f"\n\n💬 دلیل: {req.review_note}" if req.review_note else ""
    bot.notify_user(
        req.requester,
        f"❌ *درخواست نقل و انتقال رد شد*\n\n"
        f"📋 دفترچه: {booklet_code}"
        + note_suffix
        + "\n\nدر صورت نیاز با مدیریت تماس بگیرید.",
        db_session,
    )
    return jsonify(ok=True)


@bp.get("/history")
@bp.get("/transfer-history")
@login_required
def transfer_history_list():
    err = require_admin()
    if err: return err

    q          = (db_session.query(TransferHistory)
                  .join(Booklet, TransferHistory.booklet_id == Booklet.id)
                  .options(selectinload(TransferHistory.booklet).selectinload(Booklet.project),
                           selectinload(TransferHistory.from_user),
                           selectinload(TransferHistory.to_user)))
    project_id = request.args.get("project_id")
    name       = (request.args.get("name") or "").strip()
    date_from  = request.args.get("date_from")
    date_to    = request.args.get("date_to")

    if project_id:
        q = q.filter(Booklet.project_id == int(project_id))
    if name:
        q = q.join(User, TransferHistory.to_user_id == User.id).filter(
            or_(User.first_name.contains(name), User.last_name.contains(name))
        )
    if date_from:
        q = q.filter(TransferHistory.date >= date_from)
    if date_to:
        q = q.filter(TransferHistory.date <= date_to + " 23:59:59")

    items = q.order_by(TransferHistory.date.desc()).all()
    return jsonify(history=[{
        "id":           h.id,
        "date":         h.date.isoformat(),
        "booklet_code": h.booklet.code          if h.booklet               else "",
        "project_name": h.booklet.project.name  if h.booklet and h.booklet.project else "",
        "from_name":    h.from_user.full_name   if h.from_user             else "",
        "to_name":      h.to_user.full_name     if h.to_user               else "",
    } for h in items])


# ── Private helpers ───────────────────────────────────────────────────────────

def _find_or_create_new_owner(req: TransferRequest) -> User:
    """کاربر با کد ملی درخواست را پیدا یا ایجاد می‌کند."""
    new_user = (
        db_session.query(User).filter(User.national_code == req.new_owner_national_code).first()
        or db_session.query(User).filter(User.username == req.new_owner_national_code).first()
    )
    if not new_user:
        new_user = User(
            username=req.new_owner_national_code,
            password_hash=generate_password_hash(DEFAULT_NEW_OWNER_PASSWORD),
            role="member",
            first_name=req.new_owner_first_name,
            last_name=req.new_owner_last_name,
            national_code=req.new_owner_national_code,
            phone=req.new_owner_phone,
            active=True,
            profile_complete=False,
        )
        db_session.add(new_user)
        db_session.flush()
    return new_user


# فیلد فرم → (ستون روی درخواست، عنوان سند برای آرشیو، دستهٔ سند)
_TRANSFER_DOC_FIELDS = {
    "receipt":        ("receipt_path",        "فیش واریزی انتقال",   "financial"),
    "agreement":      ("agreement_path",      "قول‌نامه / توافق‌نامه", "contract"),
    "id_first_page":  ("id_first_page_path",  "شناسنامه",            "identity"),
    "national_front": ("national_front_path", "کارت ملی (جلو)",      "identity"),
    "national_back":  ("national_back_path",  "کارت ملی (پشت)",      "identity"),
    "sana_form":      ("sana_form_path",      "سند اختیاری ۱ (انتقال)", "other"),
    "extra_photo":    ("extra_photo_path",    "سند اختیاری ۲ (انتقال)", "other"),
}


def _upload_transfer_documents(req: TransferRequest) -> None:
    """
    مدارک آپلودشده را ذخیره و مسیر آن‌ها را روی درخواست تنظیم می‌کند.
    هر مدرک در آرشیو اسناد عضوِ درخواست‌دهنده هم ثبت می‌شود تا از پروندهٔ او دیده شود.
    """
    from ...models import MemberDocument

    for field, (attr, title, doc_type) in _TRANSFER_DOC_FIELDS.items():
        f = request.files.get(field)
        if not (f and f.filename):
            continue
        try:
            path = save_document(f, "requests")
        except FileValidationError:
            continue  # فایل نامعتبر را نادیده می‌گیریم — بقیه مدارک ذخیره می‌شوند
        setattr(req, attr, path)
        # ثبت در آرشیو اسناد عضو
        db_session.add(MemberDocument(
            user_id=req.requester_id,
            title=f"{title} — دفترچه {req.booklet.code if req.booklet else ''}".strip(),
            doc_type=doc_type,
            file_path=path,
            note=f"از درخواست نقل و انتقال #{req.id}",
            uploaded_by=req.requester_id,
        ))


def _notify_admins_new_request(booklet: Booklet, requester: User) -> None:
    for admin in db_session.query(User).filter_by(role="admin", active=True).all():
        db_session.add(Notification(
            user_id=admin.id,
            title="درخواست نقل و انتقال جدید",
            body=f"{requester.full_name} درخواست انتقال دفترچه {booklet.code} را ثبت کرد.",
            type="warning",
        ))


def _transfer_request_dict(r: TransferRequest) -> dict:
    b = r.booklet
    return {
        "id": r.id, "status": r.status, "booklet_id": r.booklet_id,
        "created_at": r.created_at.isoformat(),
        "new_owner_full_name":     r.new_owner_full_name,
        "new_owner_first_name":    r.new_owner_first_name,
        "new_owner_last_name":     r.new_owner_last_name,
        "new_owner_national_code": r.new_owner_national_code,
        "new_owner_phone":         r.new_owner_phone,
        "note":                    r.note or "",
        "review_note":             r.review_note or "",
        "booklet_code":            b.code            if b else "",
        "booklet_number":          b.booklet_number  if b else "",
        "booklet_serial":          b.serial          if b else "",
        "booklet_share_type":      b.share_type      if b else "",
        "booklet_contract_no":     b.contract_no     if b else "",
        "booklet_contract_date":   b.contract_date   if b else "",
        "booklet_contract_amount": b.contract_amount if b else 0,
        "project_name":            b.project.name    if b and b.project else "",
        "requester_name":          r.requester.full_name if r.requester else "",
        "receipt_path":            r.receipt_path       or "",
        "agreement_path":          r.agreement_path     or "",
        "sana_form_path":          r.sana_form_path     or "",
        "id_first_page_path":      r.id_first_page_path or "",
        "national_front_path":     r.national_front_path or "",
        "national_back_path":      r.national_back_path or "",
        "extra_photo_path":        r.extra_photo_path   or "",
    }
