"""API ماژول تنظیمات سایت و slides"""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ... import db_session
from ...models import Slide, SiteSetting
from ...utils.files import FileValidationError, save_document, save_image, save_video, detect_media_type
from ...utils.http import get_request_body, parse_int, require_admin

bp = Blueprint("settings", __name__)


# ── Settings ──────────────────────────────────────────────────────────────────

@bp.get("/admin/settings")
@bp.get("/settings")
@login_required
def settings_get():
    err = require_admin()
    if err: return err

    settings = {r.key: r.value for r in db_session.query(SiteSetting).all()}
    return jsonify(settings=settings, **settings)


@bp.post("/admin/settings")
@bp.post("/settings")
@login_required
def settings_save():
    err = require_admin()
    if err: return err

    for k, v in get_request_body().items():
        row = db_session.get(SiteSetting, k)
        if row:
            row.value = v
        else:
            db_session.add(SiteSetting(key=k, value=v))
    db_session.commit()
    return jsonify(ok=True)


@bp.post("/admin/leader-photo")
@login_required
def leader_photo_upload():
    err = require_admin()
    if err: return err

    key     = request.form.get("key", "").strip()
    allowed = {"exec_photo", "board_photo", "third_photo",
               "leader1_photo", "leader2_photo", "leader3_photo", "site_logo",
               "about_photo"}
    if key not in allowed:
        return jsonify(error="کلید نامعتبر."), 400

    f = request.files.get("photo")
    if not f or not f.filename:
        return jsonify(error="فایل انتخاب نشده."), 400

    try:
        path = save_image(f, "branding" if key == "site_logo" else "leaders")
    except FileValidationError as e:
        return jsonify(error=str(e)), 400

    row = db_session.get(SiteSetting, key)
    if row:
        row.value = path
    else:
        db_session.add(SiteSetting(key=key, value=path))
    db_session.commit()
    return jsonify(ok=True, path=path)


# ── Slides ────────────────────────────────────────────────────────────────────

@bp.get("/admin/slides")
@bp.get("/slides")
@login_required
def slides_list():
    err = require_admin()
    if err: return err

    items = db_session.query(Slide).order_by(Slide.order).all()
    return jsonify(slides=[{
        "id": s.id, "title": s.title, "subtitle": s.subtitle,
        "bg_color": s.bg_color, "order": s.order, "active": s.active,
        "image_path": s.image_path, "video_path": s.video_path,
        "media_type": getattr(s, "media_type", "image"),
    } for s in items])


@bp.post("/admin/slides")
@login_required
def slides_create():
    err = require_admin()
    if err: return err

    image_path = None
    video_path = None
    media_type = "image"

    if "video" in request.files and request.files["video"].filename:
        try:
            video_path = save_video(request.files["video"], "slides")
            media_type = "video"
        except FileValidationError as e:
            return jsonify(error=str(e)), 400
    elif "image" in request.files and request.files["image"].filename:
        try:
            image_path = save_image(request.files["image"], "slides")
        except FileValidationError as e:
            return jsonify(error=str(e)), 400

    s = Slide(
        title=request.form.get("title", ""),
        subtitle=request.form.get("subtitle"),
        bg_color=request.form.get("bg_color", "#1E2A42"),
        order=parse_int(request.form.get("order")),
        image_path=image_path,
        video_path=video_path,
        media_type=media_type,
    )
    db_session.add(s)
    db_session.commit()
    return jsonify(ok=True, id=s.id), 201


@bp.post("/admin/slides/<int:sid>")
@login_required
def slides_update(sid):
    """ویرایش اسلاید — متن، رنگ، ترتیب، وضعیت نمایش و رسانه"""
    err = require_admin()
    if err: return err

    s = db_session.get(Slide, sid)
    if not s:
        return jsonify(error="اسلاید یافت نشد."), 404

    if request.form.get("title") is not None:
        s.title = request.form.get("title", "")
    if request.form.get("subtitle") is not None:
        s.subtitle = request.form.get("subtitle") or None
    if request.form.get("bg_color"):
        s.bg_color = request.form.get("bg_color")
    if request.form.get("order") is not None:
        s.order = parse_int(request.form.get("order"))
    if request.form.get("active") is not None:
        s.active = request.form.get("active") in ("1", "true", "True")

    if "video" in request.files and request.files["video"].filename:
        try:
            s.video_path = save_video(request.files["video"], "slides")
            s.media_type = "video"
            s.image_path = None
        except FileValidationError as e:
            return jsonify(error=str(e)), 400
    elif "image" in request.files and request.files["image"].filename:
        try:
            s.image_path = save_image(request.files["image"], "slides")
            s.media_type = "image"
            s.video_path = None
        except FileValidationError as e:
            return jsonify(error=str(e)), 400

    db_session.commit()
    return jsonify(ok=True)


@bp.post("/admin/slides/<int:sid>/toggle")
@login_required
def slides_toggle(sid):
    """نمایش/پنهان کردن اسلاید"""
    err = require_admin()
    if err: return err

    s = db_session.get(Slide, sid)
    if not s:
        return jsonify(error="اسلاید یافت نشد."), 404
    s.active = not s.active
    db_session.commit()
    return jsonify(ok=True, active=s.active)


@bp.post("/admin/sms/test")
@login_required
def sms_test():
    """ارسال پیامک آزمایشی برای بررسی صحت تنظیمات sms.ir (فقط ادمین)."""
    from ... import sms
    from ...utils.validation import normalize_digits
    err = require_admin()
    if err: return err

    mobile = normalize_digits((get_request_body().get("mobile") or "").strip())
    if not mobile:
        mobile = normalize_digits(getattr(current_user, "phone", "") or "")
    if not mobile:
        return jsonify(error="شماره موبایل برای تست وارد کنید."), 400

    # اول با قالب کد تأیید، اگر نشد پیام عادی
    code = "12345"
    ok = sms.send_verify_code(mobile, code, db_session)
    if ok:
        return jsonify(ok=True, message=f"پیامک آزمایشی به {mobile} ارسال شد.")
    return jsonify(error="ارسال ناموفق بود. کلید API، شناسه قالب یا اعتبار پنل را بررسی کنید."), 400


@bp.get("/admin/sms/credit")
@login_required
def sms_credit():
    """اعتبار باقی‌ماندهٔ پنل پیامکی (فقط ادمین)."""
    from ... import sms
    err = require_admin()
    if err: return err
    credit = sms.get_credit(db_session)
    if credit is None:
        return jsonify(error="عدم دریافت اعتبار — کلید API یا اتصال را بررسی کنید."), 400
    return jsonify(ok=True, credit=credit)


@bp.post("/admin/slides/<int:sid>/delete")
@login_required
def slides_delete(sid):
    err = require_admin()
    if err: return err

    s = db_session.get(Slide, sid)
    if s:
        db_session.delete(s)
        db_session.commit()
    return jsonify(ok=True)
