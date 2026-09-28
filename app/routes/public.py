"""مسیرهای سایت عمومی (بدون نیاز به لاگین) — صفحه اصلی، پروژه‌ها، اطلاعیه‌ها، sitemap و سرو فایل‌های آپلودی."""
import os
from datetime import datetime
from flask import Blueprint, abort, render_template, send_from_directory, current_app, Response, request
from flask_login import current_user
from sqlalchemy import or_

from .. import db_session
from ..models import Announcement, Slide, Project, ProjectMember, ProjectGallery, SiteSetting, Form

bp = Blueprint("public", __name__)

# پوشه‌های حاوی مدارک حساس — فقط ادمین یا مالک فایل اجازه دارد
# marketplace: فیش پرداخت هزینه ثبت آگهی — نباید Public باشد
PROTECTED_UPLOAD_DIRS = ("requests", "payments", "member_docs", "marketplace")


def _settings():
    return {r.key: r.value for r in db_session.query(SiteSetting).all()}


@bp.get("/")
def index():
    settings      = _settings()
    slides        = db_session.query(Slide).filter_by(active=True).order_by(Slide.order).all()
    announcements = (db_session.query(Announcement)
                     .order_by(Announcement.date.desc()).limit(10).all())
    projects      = db_session.query(Project).filter_by(active=True).order_by(Project.order).all()
    # eager load members, gallery, and announcement media for public page
    for p in projects:
        _ = p.members
        _ = p.gallery
    for a in announcements:
        _ = a.media
    public_forms = (db_session.query(Form)
                    .filter_by(status='published', is_public=True)
                    .order_by(Form.created_at.desc()).all())

    recent_listings = []
    if str(settings.get("marketplace_enabled", "1")).strip().lower() in ("1", "true", "yes"):
        from datetime import datetime as _dt
        from ..models import MarketplaceListing
        recent_listings = (db_session.query(MarketplaceListing)
                           .filter(MarketplaceListing.status == "published",
                                   (MarketplaceListing.expires_at.is_(None))
                                   | (MarketplaceListing.expires_at > _dt.utcnow()))
                           .order_by(MarketplaceListing.published_at.desc().nullslast(),
                                     MarketplaceListing.created_at.desc())
                           .limit(6).all())

    return render_template("public/index.html",
                           settings=settings,
                           slides=slides,
                           announcements=announcements,
                           projects=projects,
                           public_forms=public_forms,
                           recent_listings=recent_listings)


@bp.get("/about")
def about():
    settings = _settings()
    return render_template("public/about.html", settings=settings)


@bp.get("/marketplace")
def marketplace():
    """بازار خرید و فروش دفترچه‌ها — لیست و فیلتر آگهی‌های تأییدشده (بدون نیاز به ورود)."""
    from ..models import MarketplaceListing, Project as _Project
    settings = _settings()
    if str(settings.get("marketplace_enabled", "1")).strip().lower() not in ("1", "true", "yes"):
        abort(404)

    from datetime import datetime as _dt
    q = db_session.query(MarketplaceListing).filter(
        MarketplaceListing.status == "published",
        (MarketplaceListing.expires_at.is_(None)) | (MarketplaceListing.expires_at > _dt.utcnow()),
    )
    project_id = request.args.get("project_id", type=int)
    if project_id:
        q = q.filter(MarketplaceListing.project_id == project_id)
    price_min = request.args.get("price_min", type=int)
    if price_min:
        q = q.filter(MarketplaceListing.price >= price_min)
    price_max = request.args.get("price_max", type=int)
    if price_max:
        q = q.filter(MarketplaceListing.price <= price_max)
    if request.args.get("negotiable") == "1":
        q = q.filter(MarketplaceListing.negotiable.is_(True))
    search = request.args.get("q", "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter((MarketplaceListing.title.ilike(like)) | (MarketplaceListing.code.ilike(like)))

    sort = request.args.get("sort", "newest")
    if sort == "cheapest":
        q = q.order_by(MarketplaceListing.price.asc())
    elif sort == "expensive":
        q = q.order_by(MarketplaceListing.price.desc())
    else:
        q = q.order_by(MarketplaceListing.published_at.desc().nullslast(), MarketplaceListing.created_at.desc())

    page = max(1, request.args.get("page", 1, type=int))
    per_page = 12
    total = q.count()
    listings = q.offset((page - 1) * per_page).limit(per_page).all()
    import math as _math
    projects = db_session.query(_Project).filter_by(active=True).order_by(_Project.name).all()

    return render_template("public/marketplace.html",
                           settings=settings, listings=listings, projects=projects,
                           total=total, page=page, pages=_math.ceil(total / per_page) or 1,
                           filters=request.args)


@bp.get("/marketplace/<slug>")
def marketplace_detail(slug):
    """صفحه جزئیات یک آگهی — فقط آگهی‌های منتشرشده و تأییدشده قابل مشاهده/ایندکس هستند."""
    from ..models import MarketplaceListing
    from datetime import datetime as _dt
    settings = _settings()
    if str(settings.get("marketplace_enabled", "1")).strip().lower() not in ("1", "true", "yes"):
        abort(404)
    listing = db_session.query(MarketplaceListing).filter_by(slug=slug).first()
    if not listing or listing.status != "published":
        abort(404)
    if listing.expires_at and listing.expires_at < _dt.utcnow():
        abort(404)
    return render_template("public/marketplace_detail.html", settings=settings, listing=listing)


@bp.get("/robots.txt")
def robots_txt():
    """اجازه ایندکس صفحه عمومی؛ جلوگیری از ایندکس پنل مدیریت و فرم‌های اختصاصی."""
    base = request.url_root.rstrip("/")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /dashboard/\n"
        "Disallow: /login\n"
        "Disallow: /forgot-password\n"
        "Disallow: /verify-otp\n"
        "Disallow: /reset-password\n"
        "Disallow: /api/\n"
        "Disallow: /uploads/\n"
        "Disallow: /forms/public/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@bp.get("/sitemap.xml")
def sitemap_xml():
    """نقشه سایت — فقط صفحات عمومی ایندکس‌پذیر + آگهی‌های منتشرشدهٔ بازار."""
    from ..models import MarketplaceListing
    base = request.url_root.rstrip("/")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    urls = [
        f"  <url><loc>{base}/</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>",
        f"  <url><loc>{base}/about</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>",
        f"  <url><loc>{base}/marketplace</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>0.9</priority></url>",
    ]
    listings = (db_session.query(MarketplaceListing)
                .filter_by(status="published").order_by(MarketplaceListing.published_at.desc()).limit(500).all())
    for lst in listings:
        lastmod = (lst.updated_at or lst.published_at or lst.created_at)
        lastmod_str = lastmod.strftime("%Y-%m-%d") if lastmod else today
        urls.append(f"  <url><loc>{base}/marketplace/{lst.slug}</loc>"
                    f"<lastmod>{lastmod_str}</lastmod>"
                    f"<changefreq>weekly</changefreq><priority>0.7</priority></url>")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n"
        "</urlset>\n"
    )
    return Response(body, mimetype="application/xml")


def _can_access_protected_file(filename: str) -> bool:
    """بررسی مجوز دسترسی به فایل‌های حساس (مدارک انتقال و فیش‌های پرداخت)."""
    if not current_user.is_authenticated:
        return False
    if current_user.role == "admin":
        return True

    top = filename.split("/", 1)[0]
    if top == "requests":
        from ..models import TransferRequest
        return db_session.query(TransferRequest).filter(
            TransferRequest.requester_id == current_user.id,
            or_(
                TransferRequest.receipt_path == filename,
                TransferRequest.agreement_path == filename,
                TransferRequest.sana_form_path == filename,
                TransferRequest.id_first_page_path == filename,
                TransferRequest.national_front_path == filename,
                TransferRequest.national_back_path == filename,
                TransferRequest.extra_photo_path == filename,
            ),
        ).first() is not None
    if top == "payments":
        from ..models import Payment
        return db_session.query(Payment).filter_by(
            user_id=current_user.id, receipt_path=filename
        ).first() is not None
    if top == "member_docs":
        from ..models import MemberDocument
        return db_session.query(MemberDocument).filter_by(
            user_id=current_user.id, file_path=filename
        ).first() is not None
    if top == "marketplace":
        from ..models import MarketplaceListing
        return db_session.query(MarketplaceListing).filter_by(
            seller_id=current_user.id, payment_receipt_path=filename
        ).first() is not None
    return False


@bp.get("/uploads/<path:filename>")
def serve_upload(filename):
    # جلوگیری از path traversal
    if ".." in filename or filename.startswith("/"):
        abort(404)

    top = filename.split("/", 1)[0]
    if top in PROTECTED_UPLOAD_DIRS and not _can_access_protected_file(filename):
        abort(403)

    folder = current_app.config["UPLOAD_FOLDER"]
    return send_from_directory(folder, filename)
