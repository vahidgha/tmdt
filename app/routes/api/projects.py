"""API ماژول پروژه‌ها — CRUD پروژه، گالری و اعضای پروژه"""
from flask import Blueprint, jsonify, request
from flask_login import login_required

from ... import db_session
from ...models import Booklet, Payment, ProjectGallery, ProjectMember, TransferHistory, TransferRequest, Project
from ...utils.files import FileValidationError, detect_media_type, save_image, save_upload, save_video
from ...utils.http import get_request_body, log_activity, parse_int, require_admin

bp = Blueprint("projects", __name__)


# ── Projects ──────────────────────────────────────────────────────────────────

@bp.get("/projects")
@login_required
def projects_list():
    # این endpoint از ده‌ها صفحه مختلف (فیلتر پروژه در گزارش‌ها، حسابداری،
    # انتقال، بازار و...) صدا زده می‌شود — قبلاً برای هر پروژه با
    # len(p.booklets) کل ردیف‌های دفترچه آن پروژه لود می‌شد فقط برای شمارش؛
    # با یک کوئری تجمیعی batched جایگزین شد (N+1 → ۲ کوئری کل)
    from sqlalchemy import func
    from sqlalchemy.orm import selectinload

    items = (db_session.query(Project)
             .options(selectinload(Project.members))
             .order_by(Project.order, Project.created_at).all())
    counts = dict(
        db_session.query(Booklet.project_id, func.count(Booklet.id))
        .filter(Booklet.deleted_at.is_(None))
        .group_by(Booklet.project_id).all()
    )
    result = []
    for p in items:
        d = p.to_dict()
        d["booklet_count"] = counts.get(p.id, 0)
        d["members"] = [m.to_dict() for m in p.members]
        result.append(d)
    return jsonify(projects=result)


@bp.post("/projects")
@login_required
def projects_create():
    err = require_admin()
    if err: return err

    image_path = None
    if "image" in request.files:
        try:
            image_path = save_image(request.files["image"], "projects")
        except FileValidationError as e:
            return jsonify(error=str(e)), 400

    data = get_request_body()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(error="نام پروژه الزامی است."), 400

    p = Project(
        name=name,
        description=data.get("description"),
        address=data.get("address"),
        location=data.get("location"),
        total_booklets=parse_int(data.get("total_booklets")),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        status=data.get("status", "active"),
        order=parse_int(data.get("order")),
        image_path=image_path,
        map_lat=data.get("map_lat") or None,
        map_lon=data.get("map_lon") or None,
    )
    db_session.add(p)
    db_session.commit()
    log_activity("project_create", f"پروژه جدید: {name}", "admin")
    return jsonify(ok=True, project=p.to_dict()), 201


@bp.post("/projects/<int:pid>")
@login_required
def projects_update(pid):
    err = require_admin()
    if err: return err

    p = db_session.get(Project, pid)
    if not p:
        return jsonify(error="یافت نشد."), 404

    data = get_request_body()
    for field in ("name", "description", "address", "location", "start_date", "end_date", "status", "order"):
        val = data.get(field)
        if val is not None:
            setattr(p, field, val)

    if data.get("total_booklets"):
        p.total_booklets = parse_int(data["total_booklets"])

    if "image" in request.files:
        try:
            p.image_path = save_image(request.files["image"], "projects")
        except FileValidationError as e:
            return jsonify(error=str(e)), 400

    for field in ("map_lat", "map_lon"):
        val = request.form.get(field)
        if val is not None:
            setattr(p, field, val or None)

    db_session.commit()
    log_activity("project_update", f"ویرایش پروژه: {p.name}", "admin")
    return jsonify(ok=True)


@bp.post("/projects/<int:pid>/delete")
@bp.delete("/projects/<int:pid>")
@login_required
def projects_delete(pid):
    err = require_admin()
    if err: return err

    p = db_session.get(Project, pid)
    if not p:
        return jsonify(error="یافت نشد."), 404

    name = p.name
    for g in list(p.gallery):
        db_session.delete(g)
    for m in list(p.members):
        db_session.delete(m)
    # قبل از حذف پروژه همه دفترچه‌ها (شامل soft-delete شده‌ها) باید پاک شوند
    for b in db_session.query(Booklet).filter_by(project_id=p.id).all():
        for tr in db_session.query(TransferRequest).filter_by(booklet_id=b.id).all():
            db_session.delete(tr)
        for th in db_session.query(TransferHistory).filter_by(booklet_id=b.id).all():
            db_session.delete(th)
        for pay in db_session.query(Payment).filter_by(booklet_id=b.id).all():
            pay.booklet_id = None
        db_session.delete(b)

    db_session.flush()
    db_session.delete(p)
    db_session.commit()
    log_activity("project_delete", f"حذف پروژه: {name}", "admin")
    return jsonify(ok=True)


# ── Project Gallery ───────────────────────────────────────────────────────────

@bp.get("/projects/<int:pid>/gallery")
@login_required
def project_gallery_list(pid):
    items = (db_session.query(ProjectGallery)
             .filter_by(project_id=pid)
             .order_by(ProjectGallery.order, ProjectGallery.created_at)
             .all())
    return jsonify(gallery=[g.to_dict() for g in items])


@bp.post("/projects/<int:pid>/gallery")
@login_required
def project_gallery_upload(pid):
    err = require_admin()
    if err: return err

    p = db_session.get(Project, pid)
    if not p:
        return jsonify(error="پروژه یافت نشد."), 404
    if "file" not in request.files:
        return jsonify(error="فایلی ارسال نشد."), 400

    f = request.files["file"]
    media_type = detect_media_type(f)
    try:
        if media_type == "video":
            file_path = save_video(f, "gallery_videos")
        else:
            file_path = save_image(f, "gallery_images")
    except FileValidationError as e:
        return jsonify(error=str(e)), 400

    caption   = request.form.get("caption", "").strip() or None
    order_val = parse_int(request.form.get("order"))
    g = ProjectGallery(project_id=pid, file_path=file_path, file_type=media_type,
                       caption=caption, order=order_val)
    db_session.add(g)
    db_session.commit()
    return jsonify(ok=True, item=g.to_dict()), 201


@bp.delete("/projects/<int:pid>/gallery/<int:gid>")
@login_required
def project_gallery_delete(pid, gid):
    err = require_admin()
    if err: return err

    g = db_session.get(ProjectGallery, gid)
    if g and g.project_id == pid:
        db_session.delete(g)
        db_session.commit()
    return jsonify(ok=True)


# ── Project Members ───────────────────────────────────────────────────────────

@bp.get("/projects/<int:pid>/members")
@login_required
def project_members_list(pid):
    members = (db_session.query(ProjectMember)
               .filter_by(project_id=pid)
               .order_by(ProjectMember.order)
               .all())
    return jsonify(members=[m.to_dict() for m in members])


@bp.post("/projects/<int:pid>/members")
@login_required
def project_members_create(pid):
    err = require_admin()
    if err: return err

    if request.content_type and "multipart" in request.content_type:
        full_name  = request.form.get("full_name", "").strip()
        role       = request.form.get("role", "").strip()
        phone      = request.form.get("phone", "").strip()
        order      = parse_int(request.form.get("order"))
        photo_path = None
        if "photo" in request.files:
            try:
                photo_path = save_image(request.files["photo"], "members")
            except FileValidationError as e:
                return jsonify(error=str(e)), 400
    else:
        data       = get_request_body()
        full_name  = data.get("full_name", "").strip()
        role       = data.get("role", "").strip()
        phone      = data.get("phone", "").strip()
        order      = parse_int(data.get("order"))
        photo_path = None

    if not full_name or not role:
        return jsonify(error="نام و سمت الزامی است."), 400

    m = ProjectMember(project_id=pid, role=role, full_name=full_name,
                      phone=phone, photo_path=photo_path, order=order)
    db_session.add(m)
    db_session.commit()
    return jsonify(ok=True, member=m.to_dict()), 201


@bp.delete("/projects/<int:pid>/members/<int:mid>")
@login_required
def project_members_delete(pid, mid):
    err = require_admin()
    if err: return err

    m = db_session.get(ProjectMember, mid)
    if m and m.project_id == pid:
        db_session.delete(m)
        db_session.commit()
    return jsonify(ok=True)
