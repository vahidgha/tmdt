"""
API ماژول بازار خرید و فروش دفترچه‌ها/امتیازات اعضا (Marketplace).

معماری: از زیرساخت موجود پروژه استفاده می‌کند — بدون سیستم موازی:
  • تنظیمات   → SiteSetting (key/value عمومی، همان الگوی بقیه پنل)
  • آپلود فایل → save_document (اعتبارسنجی MIME + امضای بایت — همان تابع مشترک)
  • پیام‌رسانی  → Ticket/TicketMessage موجود (فقط یک ستون listing_id اضافه شده)
  • اعلان     → Notification موجود
  • Audit Log → log_activity موجود (category='marketplace')
  • Permission → require_admin/current_user همان الگوی همه بلوپرینت‌ها

ماشین حالت آگهی (فقط از طریق توابع این فایل قابل تغییر است):
  draft → waiting_payment → payment_review → admin_review → published
                                                  ↓rejected      ↓ (sold/cancelled/expired/disabled)
  اگر fee غیرفعال باشد: draft → admin_review (بدون مرحله پرداخت)
"""
import math
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ... import bot, db_session
from ...extensions import limiter
from ...models import (
    Booklet, MarketplaceListing, MarketplacePurchaseRequest, Notification,
    Project, Ticket, TicketMessage, User,
)
from ...utils.files import FileValidationError, save_document
from ...utils.http import get_request_body, log_activity, require_admin
from ...utils.validation import normalize_digits

bp = Blueprint("marketplace", __name__)

L = MarketplaceListing
PR = MarketplacePurchaseRequest

# فیلدهای حساس — تغییر هرکدام روی آگهی منتشرشده، آن را دوباره به بررسی ادمین می‌فرستد
_SENSITIVE_FIELDS = (
    "title", "unit_type", "area", "price", "negotiable",
    "sale_terms", "description", "contact_phone", "contact_method",
)
_ACTIVE_STATUSES = (
    L.STATUS_DRAFT, L.STATUS_WAITING_PAYMENT, L.STATUS_PAYMENT_REVIEW,
    L.STATUS_ADMIN_REVIEW, L.STATUS_PUBLISHED,
)


def _settings() -> dict:
    from ...models import SiteSetting
    return {r.key: r.value for r in db_session.query(SiteSetting).all()}


def _bool_setting(s: dict, key: str, default=False) -> bool:
    return str(s.get(key, "1" if default else "0")).strip().lower() in ("1", "true", "yes")


def _int_setting(s: dict, key: str, default: int) -> int:
    try:
        return int(s.get(key, default))
    except (TypeError, ValueError):
        return default


def _require_marketplace_enabled():
    if not _bool_setting(_settings(), "marketplace_enabled", True):
        return jsonify(error="بازار خرید و فروش در حال حاضر غیرفعال است."), 403
    return None


def _jalali_year_approx() -> int:
    now = datetime.utcnow()
    return now.year - 621 if now.month >= 3 else now.year - 622


def _gen_code(listing_id: int) -> str:
    """
    کد آگهی به‌شکل TM-<سال شمسی تقریبی>-<سریال ۵رقمی>.
    سریال از روی id واقعی رکورد (بعد از flush) گرفته می‌شود، نه از COUNT — چون
    شمارش رکوردهای موجود زیر بار همزمان (دو ثبت هم‌زمان) یا هر سناریوی حذف
    رکورد می‌تواند به تولید دو کد یکسان و خطای تداخل دیتابیس بینجامد.
    """
    return f"TM-{_jalali_year_approx()}-{listing_id:05d}"


def _listing_access(listing: MarketplaceListing) -> bool:
    return current_user.role == "admin" or listing.seller_id == current_user.id


def _sweep_expired() -> None:
    """
    آگهی‌های منتشرشده‌ای که تاریخ انقضایشان گذشته را به وضعیت Expired می‌برد.
    علاوه بر این، public_listings هم مستقل و مستقیماً expires_at را فیلتر
    می‌کند (دفاع در عمق) — این تابع فقط برای درست بودن status نمایشی در
    پنل‌هاست، نه تنها خط دفاعی برای مخفی‌ماندن آگهی منقضی از سایت عمومی.
    """
    now = datetime.utcnow()
    (db_session.query(L)
     .filter(L.status == L.STATUS_PUBLISHED, L.expires_at.isnot(None), L.expires_at < now)
     .update({L.status: L.STATUS_EXPIRED}, synchronize_session=False))
    db_session.commit()


def _ticket_accessible(t: Ticket) -> bool:
    """دسترسی عادی تیکت + دسترسی فروشندهٔ آگهی‌ای که این تیکت از آن ساخته شده."""
    if current_user.role == "admin" or t.creator_id == current_user.id:
        return True
    if t.listing_id:
        listing = db_session.get(MarketplaceListing, t.listing_id)
        return bool(listing and listing.seller_id == current_user.id)
    return False


# ── تنظیمات عمومی مقادیر برای فرم ثبت آگهی ─────────────────────────────────

@bp.get("/marketplace/config")
@login_required
def marketplace_config():
    """مقادیر جاری تنظیمات بازار — برای نمایش هزینه/مدت اعتبار در فرم ثبت آگهی."""
    s = _settings()
    return jsonify(
        enabled=_bool_setting(s, "marketplace_enabled", True),
        fee_enabled=_bool_setting(s, "marketplace_fee_enabled", True),
        fee_amount=_int_setting(s, "marketplace_fee_amount", 0),
        listing_days=_int_setting(s, "marketplace_listing_days", 30),
        payment_info=s.get("marketplace_payment_info", ""),
        max_receipt_mb=_int_setting(s, "marketplace_max_receipt_mb", 5),
    )


# ── سمت عمومی (بدون نیاز به ورود) ───────────────────────────────────────────

@bp.get("/marketplace/listings")
def public_listings():
    err = _require_marketplace_enabled()
    if err: return err
    _sweep_expired()

    q = db_session.query(L).filter(
        L.status == L.STATUS_PUBLISHED,
        (L.expires_at.is_(None)) | (L.expires_at > datetime.utcnow()),
    )
    project_id = request.args.get("project_id", type=int)
    if project_id:
        q = q.filter(L.project_id == project_id)
    price_min = request.args.get("price_min", type=int)
    if price_min:
        q = q.filter(L.price >= price_min)
    price_max = request.args.get("price_max", type=int)
    if price_max:
        q = q.filter(L.price <= price_max)
    area_min = request.args.get("area_min", type=int)
    if area_min:
        q = q.filter(L.area >= area_min)
    area_max = request.args.get("area_max", type=int)
    if area_max:
        q = q.filter(L.area <= area_max)
    unit_type = request.args.get("unit_type", "").strip()
    if unit_type:
        q = q.filter(L.unit_type == unit_type)
    if request.args.get("negotiable") == "1":
        q = q.filter(L.negotiable.is_(True))
    search = request.args.get("q", "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter((L.title.ilike(like)) | (L.description.ilike(like)) | (L.code.ilike(like)))

    sort = request.args.get("sort", "newest")
    if sort == "cheapest":
        q = q.order_by(L.price.asc())
    elif sort == "expensive":
        q = q.order_by(L.price.desc())
    else:
        q = q.order_by(L.published_at.desc().nullslast(), L.created_at.desc())

    page = max(1, request.args.get("page", 1, type=int))
    per_page = 12
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()

    projects = db_session.query(Project).filter_by(active=True).order_by(Project.name).all()
    return jsonify(
        listings=[i.to_dict() for i in items],
        total=total, page=page, pages=math.ceil(total / per_page) or 1,
        projects=[{"id": p.id, "name": p.name} for p in projects],
    )


@bp.get("/marketplace/listings/<slug>")
def public_listing_detail(slug):
    err = _require_marketplace_enabled()
    if err: return err
    listing = db_session.query(L).filter_by(slug=slug).first()
    if not listing or listing.status != L.STATUS_PUBLISHED:
        return jsonify(error="آگهی یافت نشد یا منتشر نشده است."), 404
    if listing.expires_at and listing.expires_at < datetime.utcnow():
        return jsonify(error="این آگهی منقضی شده است."), 404
    return jsonify(listing=listing.to_dict())


@bp.post("/marketplace/listings/<int:lid>/purchase-request")
@limiter.limit("5 per hour")
def submit_purchase_request(lid):
    err = _require_marketplace_enabled()
    if err: return err

    s = _settings()
    if not current_user.is_authenticated and not _bool_setting(s, "marketplace_allow_guest_requests", True):
        return jsonify(error="برای ارسال درخواست خرید ابتدا وارد شوید."), 401

    listing = db_session.get(L, lid)
    if not listing or listing.status != L.STATUS_PUBLISHED:
        return jsonify(error="آگهی یافت نشد یا منتشر نشده است."), 404
    if listing.contact_method == L.CONTACT_PHONE:
        return jsonify(error="این آگهی فقط از طریق تماس تلفنی قابل پیگیری است."), 400

    data = get_request_body()
    name  = (data.get("buyer_name")  or "").strip()
    phone = normalize_digits(data.get("buyer_phone") or "").strip()
    message = (data.get("message") or "").strip()
    if not name or not phone:
        return jsonify(error="نام و شماره موبایل الزامی است."), 400
    if len(phone) < 10 or len(phone) > 15:
        return jsonify(error="شماره موبایل نامعتبر است."), 400

    pr = PR(listing_id=listing.id, buyer_name=name, buyer_phone=phone, message=message,
            buyer_user_id=current_user.id if current_user.is_authenticated else None)
    db_session.add(pr)
    db_session.flush()

    from sqlalchemy import func as _func
    last_num = db_session.query(_func.max(Ticket.number)).scalar() or 1000
    t = Ticket(
        number=last_num + 1,
        subject=f"درخواست خرید آگهی {listing.code} — {listing.title}",
        category="marketplace", priority="normal",
        creator_id=current_user.id if current_user.is_authenticated else None,
        listing_id=listing.id,
    )
    db_session.add(t)
    db_session.flush()
    body = (f"👤 خریدار: {name}\n📱 موبایل: {phone}\n\n{message}" if message
            else f"👤 خریدار: {name}\n📱 موبایل: {phone}")
    db_session.add(TicketMessage(
        ticket_id=t.id, sender_id=current_user.id if current_user.is_authenticated else None,
        body=body, is_admin=False,
    ))
    pr.ticket_id = t.id

    db_session.add(Notification(
        user_id=listing.seller_id, type="info",
        title="درخواست خرید جدید",
        body=f"برای آگهی «{listing.title}» ({listing.code}) یک درخواست خرید جدید ثبت شد.",
    ))
    log_activity("marketplace_purchase_request", f"درخواست خرید برای آگهی {listing.code}", "marketplace")
    db_session.commit()

    if listing.seller:
        bot.notify_user(listing.seller,
            f"🛒 *درخواست خرید جدید*\n\nآگهی: {listing.title} ({listing.code})\n👤 {name}\n📱 {phone}",
            db_session)
    bot.notify_admins(f"🛒 درخواست خرید جدید برای آگهی {listing.code}", db_session)

    return jsonify(ok=True, ticket_number=t.number), 201


# ── سمت عضو (فروشنده) ───────────────────────────────────────────────────────

@bp.get("/marketplace/my-listings")
@login_required
def my_listings():
    _sweep_expired()
    items = (db_session.query(L).filter_by(seller_id=current_user.id)
             .order_by(L.created_at.desc()).all())
    return jsonify(listings=[i.to_dict(include_private=True) for i in items])


@bp.get("/marketplace/listings/<int:lid>/detail")
@login_required
def listing_detail_private(lid):
    listing = db_session.get(L, lid)
    if not listing or not _listing_access(listing):
        return jsonify(error="یافت نشد."), 404
    return jsonify(listing=listing.to_dict(include_private=True))


@bp.post("/marketplace/listings")
@login_required
def create_listing():
    err = _require_marketplace_enabled()
    if err: return err

    data = get_request_body()
    booklet_id = data.get("booklet_id")
    booklet = db_session.get(Booklet, booklet_id) if booklet_id else None
    if not booklet or booklet.deleted_at or booklet.owner_id != current_user.id:
        return jsonify(error="دفترچه انتخاب‌شده متعلق به شما نیست."), 403

    existing = (db_session.query(L)
                .filter(L.booklet_id == booklet.id, L.status.in_(_ACTIVE_STATUSES))
                .first())
    if existing:
        return jsonify(error=f"برای این دفترچه پیش‌تر آگهی «{existing.code}» با وضعیت فعال ثبت شده است."), 409

    title = (data.get("title") or "").strip()
    try:
        price = int(normalize_digits(str(data.get("price") or "0")).replace(",", ""))
    except ValueError:
        price = 0
    if not title or price <= 0:
        return jsonify(error="عنوان آگهی و قیمت فروش الزامی است."), 400

    contact_method = data.get("contact_method") or L.CONTACT_REQUEST
    if contact_method not in (L.CONTACT_PHONE, L.CONTACT_REQUEST, L.CONTACT_BOTH):
        contact_method = L.CONTACT_REQUEST
    contact_phone = (data.get("contact_phone") or current_user.phone or "").strip()[:30]
    if contact_method in (L.CONTACT_PHONE, L.CONTACT_BOTH) and not contact_phone:
        return jsonify(error="برای نمایش شماره تماس، شماره تماس الزامی است."), 400

    area = data.get("area")
    try:
        area = int(area) if area not in (None, "") else None
    except ValueError:
        area = None

    # مبلغ هزینه ثبت — همیشه از Setting سمت سرور خوانده می‌شود، هرگز از کاربر گرفته نمی‌شود
    s = _settings()
    fee_enabled = _bool_setting(s, "marketplace_fee_enabled", True)
    fee_amount  = _int_setting(s, "marketplace_fee_amount", 0) if fee_enabled else 0
    fee_required = fee_enabled and fee_amount > 0

    # کد/اسلاگ موقت یکتا (بر پایه uuid) تا رکورد flush شود و id واقعی بگیرد —
    # سپس با همان id به کد نهایی TM-<سال>-<شمارهٔ رکورد> تغییر می‌کند
    # کوتاه عمداً نگه داشته می‌شود تا حتی اگر migration پهن‌سازی ستون code
    # (30→45 کاراکتر) روی این دیتابیس اجرا/موفق نشده باشد، باز هم در ظرفیت
    # قبلی (۳۰ کاراکتر) جا شود — قبلاً "tmp-"+uuid4().hex (۳۶ کاراکتر) بود
    # که همیشه از ظرفیت اصلی رد می‌شد و ثبت هر آگهی را با DataError می‌شکست
    placeholder = f"tmp-{uuid.uuid4().hex[:20]}"
    listing = L(
        code=placeholder, slug=placeholder,
        seller_id=current_user.id, booklet_id=booklet.id, project_id=booklet.project_id,
        title=title[:200],
        unit_type=((data.get("unit_type") or "").strip() or ("تمام‌سهم" if booklet.share_type == "full" else "نیم‌سهم"))[:150],
        area=area, price=price,
        negotiable=str(data.get("negotiable")).lower() in ("1", "true", "yes"),
        sale_terms=(data.get("sale_terms") or "").strip(),
        description=(data.get("description") or "").strip(),
        contact_phone=contact_phone, contact_method=contact_method,
        fee_required=fee_required, fee_amount=fee_amount,
        status=L.STATUS_WAITING_PAYMENT if fee_required else L.STATUS_ADMIN_REVIEW,
    )
    db_session.add(listing)
    db_session.flush()
    listing.code = _gen_code(listing.id)
    listing.slug = listing.code.lower()
    log_activity("marketplace_listing_create", f"ثبت آگهی {listing.code} — {title}", "marketplace")
    db_session.commit()

    if not fee_required:
        bot.notify_admins(f"📋 آگهی جدید {listing.code} در انتظار بررسی است.", db_session)

    return jsonify(ok=True, listing=listing.to_dict(include_private=True)), 201


@bp.post("/marketplace/listings/<int:lid>")
@login_required
def edit_listing(lid):
    listing = db_session.get(L, lid)
    if not listing or not _listing_access(listing):
        return jsonify(error="یافت نشد."), 404
    if listing.status in (L.STATUS_WAITING_PAYMENT, L.STATUS_PAYMENT_REVIEW, L.STATUS_SOLD,
                           L.STATUS_CANCELLED, L.STATUS_DISABLED):
        return jsonify(error="در وضعیت فعلی، ویرایش آگهی ممکن نیست."), 400

    data = get_request_body()
    changed_sensitive = False
    if "title" in data and data["title"].strip():
        new_title = data["title"].strip()[:200]
        if new_title != listing.title: changed_sensitive = True
        listing.title = new_title
    if "unit_type" in data:
        new_unit_type = (data.get("unit_type") or "").strip()[:150]
        if new_unit_type != (listing.unit_type or ""): changed_sensitive = True
        listing.unit_type = new_unit_type
    if "area" in data:
        try:
            new_area = int(data["area"]) if data["area"] not in (None, "") else None
        except (ValueError, TypeError):
            new_area = listing.area
        if new_area != listing.area: changed_sensitive = True
        listing.area = new_area
    if "price" in data:
        try:
            new_price = int(normalize_digits(str(data["price"])).replace(",", ""))
        except ValueError:
            return jsonify(error="قیمت نامعتبر است."), 400
        if new_price <= 0:
            return jsonify(error="قیمت باید بزرگ‌تر از صفر باشد."), 400
        if new_price != listing.price: changed_sensitive = True
        listing.price = new_price
    if "negotiable" in data:
        nv = str(data["negotiable"]).lower() in ("1", "true", "yes")
        if nv != listing.negotiable: changed_sensitive = True
        listing.negotiable = nv
    if "sale_terms" in data:
        if data.get("sale_terms", "").strip() != (listing.sale_terms or ""): changed_sensitive = True
        listing.sale_terms = data.get("sale_terms", "").strip()
    if "description" in data:
        if data.get("description", "").strip() != (listing.description or ""): changed_sensitive = True
        listing.description = data.get("description", "").strip()
    if "contact_method" in data and data["contact_method"] in (L.CONTACT_PHONE, L.CONTACT_REQUEST, L.CONTACT_BOTH):
        if data["contact_method"] != listing.contact_method: changed_sensitive = True
        listing.contact_method = data["contact_method"]
    if "contact_phone" in data:
        new_phone = data.get("contact_phone", "").strip()[:30]
        if new_phone != (listing.contact_phone or ""): changed_sensitive = True
        listing.contact_phone = new_phone
    if listing.contact_method in (L.CONTACT_PHONE, L.CONTACT_BOTH) and not listing.contact_phone:
        return jsonify(error="برای نمایش شماره تماس، شماره تماس الزامی است."), 400

    was_published = listing.status == L.STATUS_PUBLISHED
    if was_published and changed_sensitive and current_user.role != "admin":
        listing.status = L.STATUS_ADMIN_REVIEW
        listing.published_at = None

    log_activity("marketplace_listing_edit", f"ویرایش آگهی {listing.code}", "marketplace")
    db_session.commit()
    return jsonify(ok=True, listing=listing.to_dict(include_private=True),
                   sent_to_review=was_published and changed_sensitive and current_user.role != "admin")


@bp.post("/marketplace/listings/<int:lid>/payment")
@login_required
def upload_listing_payment(lid):
    listing = db_session.get(L, lid)
    if not listing or listing.seller_id != current_user.id:
        return jsonify(error="یافت نشد."), 404
    if listing.status != L.STATUS_WAITING_PAYMENT:
        return jsonify(error="این آگهی در مرحله پرداخت نیست."), 400

    f = request.files.get("receipt")
    if not f or not f.filename:
        return jsonify(error="فایل فیش پرداخت الزامی است."), 400

    s = _settings()
    max_mb = _int_setting(s, "marketplace_max_receipt_mb", 5)
    f.stream.seek(0, 2)
    size = f.stream.tell()
    f.stream.seek(0)
    if size > max_mb * 1024 * 1024:
        return jsonify(error=f"حجم فایل نباید از {max_mb} مگابایت بیشتر باشد."), 400

    data = get_request_body() if request.is_json else request.form.to_dict()
    payment_date = (data.get("payment_date") or "").strip()
    tracking_code = (data.get("tracking_code") or "").strip()
    if not payment_date:
        return jsonify(error="تاریخ پرداخت الزامی است."), 400

    try:
        path = save_document(f, "marketplace")
    except FileValidationError as e:
        return jsonify(error=str(e)), 400

    listing.payment_receipt_path = path
    listing.payment_date = payment_date
    listing.payment_tracking_code = tracking_code
    listing.status = L.STATUS_PAYMENT_REVIEW
    log_activity("marketplace_payment_upload", f"آپلود فیش هزینه آگهی {listing.code}", "marketplace")
    db_session.commit()
    bot.notify_admins(f"💳 فیش هزینه آگهی {listing.code} برای بررسی ارسال شد.", db_session)
    return jsonify(ok=True, listing=listing.to_dict(include_private=True))


@bp.post("/marketplace/listings/<int:lid>/cancel")
@login_required
def cancel_listing(lid):
    listing = db_session.get(L, lid)
    if not listing or (current_user.role != "admin" and listing.seller_id != current_user.id):
        return jsonify(error="یافت نشد."), 404
    if listing.status in (L.STATUS_SOLD, L.STATUS_CANCELLED):
        return jsonify(error="این آگهی قبلاً بسته شده است."), 400
    listing.status = L.STATUS_CANCELLED
    log_activity("marketplace_listing_cancel", f"لغو آگهی {listing.code}", "marketplace")
    db_session.commit()
    return jsonify(ok=True)


@bp.post("/marketplace/listings/<int:lid>/sold")
@login_required
def mark_sold(lid):
    listing = db_session.get(L, lid)
    if not listing or (current_user.role != "admin" and listing.seller_id != current_user.id):
        return jsonify(error="یافت نشد."), 404
    if listing.status != L.STATUS_PUBLISHED:
        return jsonify(error="فقط آگهی منتشرشده قابل ثبت به‌عنوان فروخته‌شده است."), 400
    listing.status = L.STATUS_SOLD
    listing.sold_at = datetime.utcnow()
    log_activity("marketplace_listing_sold", f"فروخته‌شدن آگهی {listing.code}", "marketplace")
    db_session.commit()
    return jsonify(ok=True)


@bp.post("/marketplace/listings/<int:lid>/renew")
@login_required
def renew_listing(lid):
    listing = db_session.get(L, lid)
    if not listing or (current_user.role != "admin" and listing.seller_id != current_user.id):
        return jsonify(error="یافت نشد."), 404
    if listing.status != L.STATUS_EXPIRED:
        return jsonify(error="فقط آگهی منقضی‌شده قابل تمدید است."), 400
    days = _int_setting(_settings(), "marketplace_listing_days", 30)
    listing.status = L.STATUS_PUBLISHED
    listing.expires_at = datetime.utcnow() + timedelta(days=days)
    log_activity("marketplace_listing_renew", f"تمدید آگهی {listing.code}", "marketplace")
    db_session.commit()
    return jsonify(ok=True, listing=listing.to_dict(include_private=True))


@bp.get("/marketplace/my-requests")
@login_required
def my_purchase_requests():
    items = (db_session.query(PR).join(L, PR.listing_id == L.id)
             .filter(L.seller_id == current_user.id)
             .order_by(PR.created_at.desc()).all())
    return jsonify(requests=[r.to_dict() for r in items])


@bp.post("/marketplace/requests/<int:rid>/status")
@login_required
def update_request_status(rid):
    pr = db_session.get(PR, rid)
    if not pr or not pr.listing or (current_user.role != "admin" and pr.listing.seller_id != current_user.id):
        return jsonify(error="یافت نشد."), 404
    status = get_request_body().get("status")
    if status not in (PR.STATUS_NEW, PR.STATUS_NEGOTIATING, PR.STATUS_CONTACTED,
                       PR.STATUS_DEAL_DONE, PR.STATUS_CANCELLED):
        return jsonify(error="وضعیت نامعتبر."), 400
    pr.status = status
    db_session.commit()
    return jsonify(ok=True)


# ── سمت ادمین ────────────────────────────────────────────────────────────────

@bp.get("/marketplace/admin/listings")
@login_required
def admin_list_listings():
    err = require_admin()
    if err: return err
    _sweep_expired()
    q = db_session.query(L).order_by(L.created_at.desc())
    status = request.args.get("status", "").strip()
    if status:
        q = q.filter(L.status == status)
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify(listings=[i.to_dict(include_private=True) for i in items],
                   total=total, page=page, pages=math.ceil(total / per_page) or 1)


@bp.get("/marketplace/admin/listings/<int:lid>")
@login_required
def admin_listing_detail(lid):
    err = require_admin()
    if err: return err
    listing = db_session.get(L, lid)
    if not listing:
        return jsonify(error="یافت نشد."), 404

    from ...models import ActivityLog
    logs = (db_session.query(ActivityLog)
            .filter(ActivityLog.category == "marketplace", ActivityLog.detail.ilike(f"%{listing.code}%"))
            .order_by(ActivityLog.created_at.desc()).all())
    return jsonify(
        listing=listing.to_dict(include_private=True),
        purchase_requests=[r.to_dict() for r in listing.purchase_requests],
        history=[{"action": lg.action, "detail": lg.detail,
                  "user": lg.user.full_name if lg.user else "—",
                  "created_at": lg.created_at.isoformat()} for lg in logs],
    )


@bp.post("/marketplace/admin/listings/<int:lid>/approve-payment")
@login_required
def admin_approve_payment(lid):
    err = require_admin()
    if err: return err
    listing = db_session.get(L, lid)
    if not listing or listing.status != L.STATUS_PAYMENT_REVIEW:
        return jsonify(error="این آگهی در مرحله بررسی پرداخت نیست."), 400
    listing.status = L.STATUS_ADMIN_REVIEW
    listing.payment_reviewed_by = current_user.id
    listing.payment_reviewed_at = datetime.utcnow()
    log_activity("marketplace_payment_approve", f"تأیید پرداخت آگهی {listing.code}", "marketplace")
    db_session.commit()
    if listing.seller:
        bot.notify_user(listing.seller, f"✅ پرداخت هزینه آگهی {listing.code} تأیید شد و در صف بررسی نهایی قرار گرفت.", db_session)
    return jsonify(ok=True)


@bp.post("/marketplace/admin/listings/<int:lid>/reject-payment")
@login_required
def admin_reject_payment(lid):
    err = require_admin()
    if err: return err
    listing = db_session.get(L, lid)
    if not listing or listing.status != L.STATUS_PAYMENT_REVIEW:
        return jsonify(error="این آگهی در مرحله بررسی پرداخت نیست."), 400
    reason = (get_request_body().get("reason") or "").strip()
    if not reason:
        return jsonify(error="دلیل رد پرداخت الزامی است."), 400
    listing.status = L.STATUS_WAITING_PAYMENT
    listing.reject_reason = reason
    listing.payment_reviewed_by = current_user.id
    listing.payment_reviewed_at = datetime.utcnow()
    log_activity("marketplace_payment_reject", f"رد پرداخت آگهی {listing.code} — {reason}", "marketplace")
    db_session.commit()
    if listing.seller:
        bot.notify_user(listing.seller, f"❌ فیش پرداخت آگهی {listing.code} رد شد: {reason}\nلطفاً دوباره فیش صحیح را ارسال کنید.", db_session)
    return jsonify(ok=True)


@bp.post("/marketplace/admin/listings/<int:lid>/approve")
@login_required
def admin_approve_listing(lid):
    err = require_admin()
    if err: return err
    listing = db_session.get(L, lid)
    if not listing or listing.status != L.STATUS_ADMIN_REVIEW:
        return jsonify(error="این آگهی در مرحله بررسی نهایی نیست."), 400
    days = _int_setting(_settings(), "marketplace_listing_days", 30)
    listing.status = L.STATUS_PUBLISHED
    listing.published_at = datetime.utcnow()
    listing.expires_at = datetime.utcnow() + timedelta(days=days)
    listing.admin_reviewed_by = current_user.id
    listing.admin_reviewed_at = datetime.utcnow()
    listing.reject_reason = None
    log_activity("marketplace_listing_approve", f"تأیید و انتشار آگهی {listing.code}", "marketplace")
    db_session.commit()
    if listing.seller:
        bot.notify_user(listing.seller, f"🎉 آگهی «{listing.title}» ({listing.code}) تأیید و در بازار منتشر شد.", db_session)
    return jsonify(ok=True)


@bp.post("/marketplace/admin/listings/<int:lid>/reject")
@login_required
def admin_reject_listing(lid):
    err = require_admin()
    if err: return err
    listing = db_session.get(L, lid)
    if not listing or listing.status not in (L.STATUS_ADMIN_REVIEW, L.STATUS_PUBLISHED):
        return jsonify(error="در وضعیت فعلی این آگهی قابل رد نیست."), 400
    reason = (get_request_body().get("reason") or "").strip()
    if not reason:
        return jsonify(error="دلیل رد آگهی الزامی است."), 400
    listing.status = L.STATUS_REJECTED
    listing.reject_reason = reason
    listing.admin_reviewed_by = current_user.id
    listing.admin_reviewed_at = datetime.utcnow()
    listing.published_at = None
    log_activity("marketplace_listing_reject", f"رد آگهی {listing.code} — {reason}", "marketplace")
    db_session.commit()
    if listing.seller:
        bot.notify_user(listing.seller, f"❌ آگهی «{listing.title}» ({listing.code}) رد شد: {reason}", db_session)
    return jsonify(ok=True)


@bp.post("/marketplace/admin/listings/<int:lid>/disable")
@login_required
def admin_disable_listing(lid):
    err = require_admin()
    if err: return err
    listing = db_session.get(L, lid)
    if not listing:
        return jsonify(error="یافت نشد."), 404
    listing.status = L.STATUS_DISABLED
    log_activity("marketplace_listing_disable", f"غیرفعال‌سازی آگهی {listing.code}", "marketplace")
    db_session.commit()
    return jsonify(ok=True)


@bp.get("/marketplace/admin/stats")
@login_required
def admin_stats():
    err = require_admin()
    if err: return err
    from sqlalchemy import func
    counts = dict(db_session.query(L.status, func.count(L.id)).group_by(L.status).all())
    revenue = (db_session.query(func.coalesce(func.sum(L.fee_amount), 0))
               .filter(L.status.in_((L.STATUS_PAYMENT_REVIEW, L.STATUS_ADMIN_REVIEW,
                                      L.STATUS_PUBLISHED, L.STATUS_SOLD, L.STATUS_EXPIRED)))
               .filter(L.fee_required.is_(True))
               .scalar() or 0)
    return jsonify(
        total=sum(counts.values()),
        published=counts.get(L.STATUS_PUBLISHED, 0),
        pending_review=counts.get(L.STATUS_ADMIN_REVIEW, 0),
        pending_payment_review=counts.get(L.STATUS_PAYMENT_REVIEW, 0),
        sold=counts.get(L.STATUS_SOLD, 0),
        expired=counts.get(L.STATUS_EXPIRED, 0),
        rejected=counts.get(L.STATUS_REJECTED, 0),
        purchase_requests=db_session.query(func.count(PR.id)).scalar() or 0,
        revenue=revenue,
    )
