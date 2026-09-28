"""API ماژول اطلاعیه‌ها"""
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ... import db_session
from ...models import Announcement, AnnouncementMedia
from ... import bot
from ...utils.files import FileValidationError, detect_media_type, save_image, save_video
from ...utils.http import get_field, get_request_body, log_activity, require_admin

bp = Blueprint("announcements", __name__)


def _parse_datetime(val: str):
    """رشته ISO 8601 را به datetime تبدیل می‌کند. در صورت خطا None برمی‌گرداند."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00").replace("+00:00", ""))
    except Exception:
        return None


@bp.get("/announcements")
@login_required
def announcements_list():
    items = db_session.query(Announcement).order_by(Announcement.date.desc()).all()
    now   = datetime.utcnow()
    result = []
    for a in items:
        if current_user.role != "admin":
            if a.pub_date and a.pub_date > now:
                continue
            if a.expires_at and a.expires_at < now:
                continue
        result.append({
            "id": a.id, "title": a.title, "body": a.body,
            "author": a.author, "date": a.date.isoformat(),
            "image_path": a.image_path or "",
            "project_id": a.project_id,
            "project_name": a.project.name if a.project else None,
            "pub_date":   a.pub_date.isoformat()   if a.pub_date   else None,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
            "media": [m.to_dict() for m in a.media],
        })
    return jsonify(announcements=result)


@bp.post("/announcements")
@login_required
def announcements_create():
    err = require_admin()
    if err: return err

    title = get_field("title").strip()
    body  = get_field("body").strip()
    if not title or not body:
        return jsonify(error="عنوان و متن الزامی است."), 400

    image_path = None
    if not request.is_json and "image" in request.files and request.files["image"].filename:
        try:
            image_path = save_image(request.files["image"], "announcements")
        except FileValidationError as e:
            return jsonify(error=str(e)), 400

    pid = get_field("project_id") or None
    a = Announcement(
        title=title, body=body, image_path=image_path,
        author=current_user.full_name, author_id=current_user.id,
        project_id=int(pid) if pid else None,
        pub_date=_parse_datetime(get_field("pub_date")),
        expires_at=_parse_datetime(get_field("expires_at")),
    )
    db_session.add(a)
    db_session.commit()
    log_activity("announcement_create", f"اطلاعیه جدید: {title}", "admin")

    preview = body[:300] + ("..." if len(body) > 300 else "")
    bot.notify_all_members(f"📢 *اطلاعیه جدید*\n\n*{title}*\n\n{preview}", db_session)
    return jsonify(ok=True, id=a.id), 201


@bp.post("/announcements/<int:aid>")
@login_required
def announcements_update(aid):
    err = require_admin()
    if err: return err

    a = db_session.get(Announcement, aid)
    if not a:
        return jsonify(error="یافت نشد."), 404

    title = (request.form.get("title") or "").strip()
    body  = (request.form.get("body")  or "").strip()
    if not title or not body:
        return jsonify(error="عنوان و متن الزامی است."), 400

    a.title = title
    a.body  = body
    if "image" in request.files and request.files["image"].filename:
        try:
            a.image_path = save_image(request.files["image"], "announcements")
        except FileValidationError as e:
            return jsonify(error=str(e)), 400

    pid = request.form.get("project_id") or None
    a.project_id = int(pid) if pid else None
    a.pub_date   = _parse_datetime(request.form.get("pub_date"))
    a.expires_at = _parse_datetime(request.form.get("expires_at"))
    db_session.commit()
    log_activity("announcement_update", f"ویرایش اطلاعیه: {a.title}", "admin")
    return jsonify(ok=True)


@bp.delete("/announcements/<int:aid>")
@login_required
def announcements_delete(aid):
    err = require_admin()
    if err: return err

    a = db_session.get(Announcement, aid)
    if not a:
        return jsonify(error="یافت نشد."), 404

    title = a.title
    for m in list(a.media):
        db_session.delete(m)
    db_session.flush()
    db_session.delete(a)
    db_session.commit()
    log_activity("announcement_delete", f"حذف اطلاعیه: {title}", "admin")
    return jsonify(ok=True)


@bp.post("/announcements/<int:aid>/media")
@login_required
def announcement_media_upload(aid):
    err = require_admin()
    if err: return err

    a = db_session.get(Announcement, aid)
    if not a:
        return jsonify(error="اطلاعیه یافت نشد."), 404
    if "file" not in request.files:
        return jsonify(error="فایلی ارسال نشد."), 400

    f          = request.files["file"]
    media_type = detect_media_type(f)
    try:
        if media_type == "video":
            file_path = save_video(f, "ann_videos")
        else:
            file_path = save_image(f, "ann_images")
    except FileValidationError as e:
        return jsonify(error=str(e)), 400

    caption   = request.form.get("caption", "").strip() or None
    order_val = int(request.form.get("order", 0) or 0)
    m = AnnouncementMedia(
        announcement_id=aid, file_path=file_path,
        file_type=media_type, caption=caption, order=order_val,
    )
    db_session.add(m)
    db_session.commit()
    return jsonify(ok=True, item=m.to_dict()), 201


@bp.delete("/announcements/<int:aid>/media/<int:mid>")
@login_required
def announcement_media_delete(aid, mid):
    err = require_admin()
    if err: return err

    m = db_session.get(AnnouncementMedia, mid)
    if m and m.announcement_id == aid:
        db_session.delete(m)
        db_session.commit()
    return jsonify(ok=True)
