"""API ماژول دفترچه‌ها"""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from ... import db_session
from ...models import Booklet, Payment, SiteSetting, TransferHistory, TransferRequest
from ...utils.http import get_request_body, log_activity, parse_int, require_admin

bp = Blueprint("booklets", __name__)


@bp.get("/booklets")
@login_required
def booklets_list():
    """لیست دفترچه‌ها — admin همه، member فقط خودش"""
    if current_user.role == "admin":
        items = (db_session.query(Booklet)
                 .filter(Booklet.deleted_at.is_(None))
                 .options(selectinload(Booklet.project), selectinload(Booklet.owner))
                 .order_by(Booklet.created_at.desc())
                 .all())
    else:
        items = current_user.booklets
    return jsonify(booklets=[b.to_dict() for b in items])


@bp.post("/booklets")
@login_required
def booklets_create():
    """ثبت دفترچه جدید برای عضو موجود"""
    from ...models import Project, User
    err = require_admin()
    if err: return err

    data = get_request_body()
    if not all(data.get(k) for k in ("owner_id", "project_id", "share_type")):
        return jsonify(error="owner_id، project_id و share_type الزامی است."), 400

    proj = db_session.get(Project, parse_int(data["project_id"]))
    if not proj:
        return jsonify(error="پروژه یافت نشد."), 404

    owner = db_session.get(User, parse_int(data["owner_id"]))
    if not owner:
        return jsonify(error="عضو یافت نشد."), 404

    last_serial = db_session.query(func.max(Booklet.serial)).filter_by(project_id=proj.id).scalar() or 0
    serial      = last_serial + 1
    c_no        = data.get("contract_no", "")
    code        = c_no.strip() if c_no and c_no.strip() else f"ZNJ-{proj.id:03d}-{serial:04d}"

    # شماره قرارداد/کد فقط باید در همان پروژه یکتا باشد — دو پروژه مختلف
    # می‌توانند هر دو یک شماره قرارداد مشابه (مثلاً «۳») داشته باشند
    dup = db_session.query(Booklet).filter_by(project_id=proj.id, code=code, deleted_at=None).first()
    if dup:
        owner_name = f"{dup.owner.first_name} {dup.owner.last_name}".strip() if dup.owner else "؟"
        return jsonify(error=(
            f"کد دفترچه «{code}» قبلاً برای دفترچه دیگری در همین پروژه ثبت شده "
            f"(عضو: {owner_name}) — شماره قرارداد دیگری وارد کنید یا آن دفترچه را حذف کنید."
        )), 409

    # اگر کد فقط روی یک دفترچهٔ حذف‌شدهٔ قدیمی همین پروژه مانده باشد (که به هر
    # دلیلی آزاد نشده)، همین‌جا آن را آزاد می‌کنیم تا قید یکتایی مانع ساخت
    # دفترچه جدید نشود
    stale = db_session.query(Booklet).filter(
        Booklet.project_id == proj.id, Booklet.code == code, Booklet.deleted_at.isnot(None)
    ).first()
    if stale:
        stale.code = f"DEL{stale.id}-{stale.code}"[:30]

    b = Booklet(
        code=code,
        serial=serial,
        booklet_number=data.get("booklet_number", ""),
        project_id=proj.id,
        owner_id=owner.id,
        share_type=data["share_type"],
        contract_no=c_no,
        contract_date=data.get("contract_date", ""),
        contract_amount=parse_int(data.get("contract_amount")),
        notes=data.get("notes"),
    )
    db_session.add(b)
    db_session.commit()
    log_activity("booklet_create", f"دفترچه جدید: {b.code} — {proj.name}", "booklet")
    return jsonify(ok=True, booklet=b.to_dict()), 201


@bp.delete("/booklets/<int:bid>")
@login_required
def booklets_delete(bid):
    """
    Soft delete — دفترچه مخفی می‌شود اما رکورد، پرداخت‌ها و سابقه
    نقل و انتقال آن برای حسابرسی حفظ می‌ماند.
    """
    from datetime import datetime
    err = require_admin()
    if err: return err

    b = db_session.get(Booklet, bid)
    if not b or b.deleted_at:
        return jsonify(error="یافت نشد."), 404

    b.deleted_at = datetime.utcnow()
    # کد دفترچه آزاد می‌شود تا بشود دوباره برای دفترچه جدیدی از همان شماره قرارداد
    # استفاده کرد — چون ستون code یکتاست و حذف فقط soft-delete است (رکورد اصلی
    # برای حسابرسی می‌ماند)، بدون این تغییر، کد قدیمی برای همیشه اشغال می‌ماند.
    b.code = f"DEL{b.id}-{b.code}"[:30]
    # درخواست‌های در انتظار این دفترچه دیگر معنا ندارند
    for tr in db_session.query(TransferRequest).filter_by(booklet_id=bid, status="pending").all():
        tr.status      = "rejected"
        tr.review_note = "دفترچه توسط مدیریت حذف شد."
        tr.reviewed_at = datetime.utcnow()

    db_session.commit()
    log_activity("booklet_delete", f"حذف دفترچه: {b.code}", "booklet")
    return jsonify(ok=True)


@bp.get("/booklets/<int:bid>/contract")
@login_required
def booklets_contract(bid):
    """اطلاعات کامل دفترچه برای چاپ قرارداد"""
    b = db_session.get(Booklet, bid)
    if not b or b.deleted_at:
        return jsonify(error="یافت نشد."), 404
    if current_user.role == "member" and b.owner_id != current_user.id:
        return jsonify(error="دسترسی ندارید."), 403

    settings = {r.key: r.value for r in db_session.query(SiteSetting).all()}
    return jsonify(
        booklet=b.to_dict(),
        owner=b.owner.to_dict(),
        project=b.project.to_dict(),
        settings=settings,
    )
