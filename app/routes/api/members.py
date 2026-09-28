"""API ماژول اعضا — CRUD اعضا، import/export اکسل"""
import io
import math

from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from werkzeug.security import generate_password_hash

from ... import db_session
from ...models import (Announcement, Booklet, Notification, Payment,
                       Project, Ticket, TransferHistory, TransferRequest, User)
from ...utils.http import get_request_body, log_activity, parse_int, require_admin
from ...utils.validation import validate_user_fields

bp = Blueprint("members", __name__)


def _booklet_code(contract_no: str, project_id: int, serial: int) -> str:
    """کد دفترچه = شماره قرارداد؛ در صورت خالی بودن: ZNJ-پروژه-سریال"""
    if contract_no and contract_no.strip():
        return contract_no.strip()
    return f"ZNJ-{project_id:03d}-{serial:04d}"


# ── Members ───────────────────────────────────────────────────────────────────

@bp.get("/members")
@login_required
def members_list():
    """
    لیست اعضا با جستجو و صفحه‌بندی سمت سرور.
    پارامترها (همه اختیاری):
      project_id — فیلتر پروژه
      search     — جستجو در نام، کد ملی، موبایل و نام کاربری
      page       — شماره صفحه (بدون آن، همه برگردانده می‌شود = سازگاری قبلی)
      per_page   — اندازه صفحه (پیش‌فرض ۵۰، حداکثر ۲۰۰)
    """
    import math
    from sqlalchemy import or_

    err = require_admin()
    if err: return err

    project_id = request.args.get("project_id")
    search     = (request.args.get("search") or "").strip()
    page       = request.args.get("page", type=int)
    per_page   = min(request.args.get("per_page", 50, type=int) or 50, 200)

    q = db_session.query(User).filter(User.role == "member")
    if project_id:
        q = (q.join(Booklet, Booklet.owner_id == User.id)
              .filter(Booklet.project_id == int(project_id),
                      Booklet.deleted_at.is_(None))
              .distinct())
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            User.first_name.ilike(like),
            User.last_name.ilike(like),
            User.national_code.ilike(like),
            User.phone.ilike(like),
            User.username.ilike(like),
        ))

    q     = q.order_by(User.last_name, User.first_name)
    total = q.count()

    # eager-load دفترچه‌ها + پروژه/مالک هر دفترچه در ۲ کوئری batched به‌جای
    # N+1 (قبلاً برای هر عضو یک کوئری دفترچه و برای هر دفترچه یک کوئری پروژه
    # جداگانه اجرا می‌شد — روی لیست چندصد عضوی به صدها کوئری می‌رسید)
    q = q.options(selectinload(User.booklets).selectinload(Booklet.project),
                  selectinload(User.booklets).selectinload(Booklet.owner))

    if page:
        members = q.offset((page - 1) * per_page).limit(per_page).all()
        pages   = math.ceil(total / per_page) or 1
    else:
        members = q.all()
        pages   = 1

    return jsonify(
        members=[{**m.to_dict(), "booklets": [b.to_dict() for b in m.booklets]}
                 for m in members],
        total=total, page=page or 1, pages=pages,
    )


@bp.post("/members")
@login_required
def members_create():
    err = require_admin()
    if err: return err

    data = get_request_body()
    required_fields = ("first_name", "last_name", "username", "password")
    if not all(data.get(k) for k in required_fields):
        return jsonify(error="نام، نام خانوادگی، نام کاربری و رمز عبور الزامی است."), 400

    v_err = validate_user_fields(data)
    if v_err:
        return jsonify(error=v_err), 400

    if db_session.query(User).filter_by(username=data["username"]).first():
        return jsonify(error="این نام کاربری قبلاً ثبت شده."), 409

    nat = (data.get("national_code") or "").strip()
    if nat and db_session.query(User).filter_by(national_code=nat).first():
        return jsonify(error="عضوی با این کد ملی قبلاً ثبت شده."), 409

    user = User(
        username=data["username"],
        password_hash=generate_password_hash(data["password"]),
        role="member",
        first_name=data["first_name"],
        last_name=data["last_name"],
        national_code=data.get("national_code"),
        gender=data.get("gender"),
        id_number=data.get("id_number"),
        phone=data.get("phone"),
        emergency_phone=data.get("emergency_phone"),
        father_name=data.get("father_name"),
        birth_date=data.get("birth_date"),
        landline=data.get("landline"),
        address=data.get("address"),
        postal_code=data.get("postal_code"),
        active=True,
        profile_complete=True,
    )
    db_session.add(user)
    db_session.flush()
    log_activity("member_create", f"عضو جدید: {user.full_name} ({user.username})", "member")

    if data.get("project_id"):
        booklet_err = _create_booklet_for_user(user, data)
        if booklet_err:
            db_session.rollback()
            return jsonify(error=booklet_err), 409

    db_session.commit()
    return jsonify(ok=True, member=user.to_dict()), 201


_EDITABLE_MEMBER_FIELDS = [
    "first_name", "last_name", "national_code", "gender", "id_number",
    "phone", "emergency_phone", "father_name", "birth_date", "birth_place",
    "marital_status", "landline", "address", "postal_code", "occupation",
    "email", "bank_name", "account_number", "iban",
]


@bp.get("/members/<int:uid>")
@login_required
def member_get(uid):
    """جزئیات یک عضو برای ویرایش (فقط ادمین)."""
    err = require_admin()
    if err: return err
    u = db_session.get(User, uid)
    if not u:
        return jsonify(error="یافت نشد."), 404
    return jsonify(member={**u.to_dict(), "booklets": [b.to_dict() for b in u.booklets]})


@bp.post("/members/<int:uid>")
@login_required
def member_update(uid):
    """ویرایش اطلاعات عضو توسط مدیر."""
    err = require_admin()
    if err: return err

    u = db_session.get(User, uid)
    if not u:
        return jsonify(error="یافت نشد."), 404

    data = get_request_body()

    # اعتبارسنجی طول و فرمت (نرمال‌سازی ارقام فارسی داخل validate)
    check = {f: (data[f] if data.get(f) is not None else getattr(u, f))
             for f in _EDITABLE_MEMBER_FIELDS if f in data}
    v_err = validate_user_fields(check)
    if v_err:
        return jsonify(error=v_err), 400

    # یکتایی کد ملی
    new_nat = check.get("national_code")
    if new_nat and new_nat != (u.national_code or ""):
        dup = db_session.query(User).filter(User.national_code == new_nat, User.id != uid).first()
        if dup:
            return jsonify(error="عضو دیگری با این کد ملی وجود دارد."), 409

    for f in _EDITABLE_MEMBER_FIELDS:
        if f in data:
            setattr(u, f, check.get(f) or None)

    # تغییر نام کاربری (اختیاری، با بررسی یکتایی)
    new_username = (data.get("username") or "").strip()
    if new_username and new_username != u.username:
        if db_session.query(User).filter(User.username == new_username, User.id != uid).first():
            return jsonify(error="این نام کاربری قبلاً ثبت شده."), 409
        u.username = new_username

    db_session.commit()
    log_activity("member_update", f"ویرایش عضو: {u.full_name} ({u.username})", "member")
    return jsonify(ok=True, member=u.to_dict())


@bp.post("/members/<int:uid>/password")
@login_required
def member_set_password(uid):
    """تغییر رمز عبور عضو توسط مدیر."""
    err = require_admin()
    if err: return err

    u = db_session.get(User, uid)
    if not u:
        return jsonify(error="یافت نشد."), 404
    if u.role == "admin" and u.id != current_user.id:
        return jsonify(error="تغییر رمز مدیر دیگر مجاز نیست."), 403

    pw = (get_request_body().get("password") or "").strip()
    if len(pw) < 4:
        return jsonify(error="رمز عبور باید حداقل ۴ کاراکتر باشد."), 400

    u.password_hash = generate_password_hash(pw)
    db_session.commit()
    log_activity("member_password_reset", f"تغییر رمز عضو: {u.full_name}", "member")
    return jsonify(ok=True)


@bp.get("/finance-users")
@login_required
def finance_users_list():
    """کاربران دارای نقش مالی + اعضای قابل ارتقا (فقط ادمین)"""
    err = require_admin()
    if err: return err
    finance = db_session.query(User).filter_by(role="finance").order_by(User.last_name).all()
    return jsonify(finance_users=[
        {"id": u.id, "full_name": u.full_name, "username": u.username,
         "national_code": u.national_code or ""}
        for u in finance
    ])


@bp.post("/members/<int:uid>/set-role")
@login_required
def members_set_role(uid):
    """
    تغییر نقش بین 'member' و 'finance' (فقط ادمین).
    نقش admin از این مسیر قابل تنظیم نیست.
    """
    err = require_admin()
    if err: return err

    u = db_session.get(User, uid)
    if not u:
        return jsonify(error="کاربر یافت نشد."), 404
    if u.role == "admin":
        return jsonify(error="نقش مدیر از این مسیر تغییر نمی‌کند."), 400

    new_role = (get_request_body().get("role") or "").strip()
    if new_role not in ("member", "finance"):
        return jsonify(error="نقش نامعتبر."), 400

    u.role = new_role
    db_session.commit()
    label = "مسئول مالی" if new_role == "finance" else "عضو عادی"
    log_activity("member_set_role", f"{u.full_name} → {label}", "admin")
    return jsonify(ok=True, role=new_role)


@bp.post("/members/<int:uid>/toggle")
@login_required
def members_toggle(uid):
    err = require_admin()
    if err: return err

    u = db_session.get(User, uid)
    if not u:
        return jsonify(error="یافت نشد."), 404

    u.active = not u.active
    db_session.commit()
    label = "فعال‌سازی" if u.active else "غیرفعال‌سازی"
    log_activity("member_toggle", f"{label} عضو: {u.full_name}", "member")
    return jsonify(ok=True, active=u.active)


@bp.delete("/members/<int:uid>")
@login_required
def members_delete(uid):
    err = require_admin()
    if err: return err

    u = db_session.get(User, uid)
    if not u:
        return jsonify(error="یافت نشد."), 404
    if u.role == "admin":
        return jsonify(error="حذف مدیر مجاز نیست."), 403

    name = u.full_name
    _cascade_delete_user(u)
    db_session.flush()
    db_session.delete(u)
    db_session.commit()
    log_activity("delete_member", f"حذف عضو: {name}")
    return jsonify(ok=True)


# ── Member Documents (آرشیو اسناد عضو) ────────────────────────────────────────

@bp.get("/members/<int:uid>/documents")
@login_required
def member_documents_list(uid):
    """لیست اسناد یک عضو — ادمین یا خود عضو"""
    from flask_login import current_user
    from ...models import MemberDocument
    if current_user.role != "admin" and current_user.id != uid:
        return jsonify(error="دسترسی ندارید."), 403
    docs = (db_session.query(MemberDocument)
            .filter_by(user_id=uid)
            .order_by(MemberDocument.created_at.desc())
            .all())
    return jsonify(documents=[d.to_dict() for d in docs])


@bp.post("/members/<int:uid>/documents")
@login_required
def member_documents_upload(uid):
    """آپلود سند برای عضو (فقط ادمین)"""
    from flask_login import current_user
    from ...models import MemberDocument
    from ...utils.files import FileValidationError, save_document

    err = require_admin()
    if err: return err

    u = db_session.get(User, uid)
    if not u:
        return jsonify(error="عضو یافت نشد."), 404

    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="فایل انتخاب نشده."), 400

    title = (request.form.get("title") or "").strip()
    if not title:
        return jsonify(error="عنوان سند الزامی است."), 400

    doc_type = request.form.get("doc_type", "other")
    if doc_type not in ("contract", "identity", "financial", "other"):
        doc_type = "other"

    try:
        path = save_document(f, "member_docs")
    except FileValidationError as e:
        return jsonify(error=str(e)), 400

    doc = MemberDocument(
        user_id=uid, title=title, doc_type=doc_type,
        file_path=path, note=request.form.get("note") or None,
        uploaded_by=current_user.id,
    )
    db_session.add(doc)
    db_session.commit()
    log_activity("member_doc_upload", f"سند «{title}» برای {u.full_name}", "member")
    return jsonify(ok=True, document=doc.to_dict()), 201


@bp.delete("/members/<int:uid>/documents/<int:did>")
@login_required
def member_documents_delete(uid, did):
    """حذف سند عضو (فقط ادمین)"""
    from ...models import MemberDocument
    err = require_admin()
    if err: return err

    doc = db_session.get(MemberDocument, did)
    if not doc or doc.user_id != uid:
        return jsonify(error="یافت نشد."), 404

    title = doc.title
    db_session.delete(doc)
    db_session.commit()
    log_activity("member_doc_delete", f"حذف سند «{title}»", "member")
    return jsonify(ok=True)


# ── Excel Template & Import ───────────────────────────────────────────────────

@bp.get("/members/template")
@login_required
def members_excel_template():
    """دانلود فایل اکسل نمونه برای وارد کردن اعضا"""
    err = require_admin()
    if err: return err

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb   = Workbook()
    ws   = wb.active
    ws.title                = "اعضا"
    ws.sheet_view.rightToLeft = True

    COLS = _excel_column_definitions()
    projects     = db_session.query(Project).filter_by(active=True).order_by(Project.name).all()
    project_names = [p.name for p in projects]

    _build_excel_header(ws, COLS)
    _build_excel_example_row(ws, COLS, project_names)
    _add_excel_validations(ws, wb, COLS, project_names)
    ws.freeze_panes = "A4"
    _build_excel_guide_sheet(wb, COLS)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="members_template.xlsx",
    )


@bp.post("/members/import")
@login_required
def members_import():
    """ورود انبوه اعضا از فایل اکسل"""
    err = require_admin()
    if err: return err

    if "file" not in request.files:
        return jsonify(error="فایل انتخاب نشده."), 400
    f = request.files["file"]
    if not f.filename.endswith((".xlsx", ".xls")):
        return jsonify(error="فرمت فایل باید xlsx باشد."), 400

    from openpyxl import load_workbook
    try:
        wb = load_workbook(filename=f, read_only=True, data_only=True)
    except Exception:
        return jsonify(error="فایل اکسل معتبر نیست."), 400

    ws         = wb.active
    header_row = _find_excel_header(ws)
    if header_row is None:
        return jsonify(error="هدر ستون‌ها پیدا نشد. مطمئن شوید از تمپلیت اصلی استفاده می‌کنید."), 400

    col_idx = _build_column_index(header_row)
    created, skipped, errors = [], [], []

    data_started = False
    for row_num, row in enumerate(ws.iter_rows(values_only=True), start=1):
        row_vals = [str(c or "").strip() for c in row]
        if not data_started:
            if any("نام کاربری" in v for v in row_vals):
                data_started = True
            continue

        result = _import_single_row(row_num, row_vals, col_idx, created, skipped, errors)
        if result == "skip":
            continue

    try:
        db_session.commit()
    except Exception as ex:
        db_session.rollback()
        return jsonify(error=f"خطا در ذخیره‌سازی: {ex}"), 500

    return jsonify(
        ok=True,
        created=len(created),
        skipped=len(skipped),
        errors=len(errors),
        detail={"created": created, "skipped": skipped, "errors": errors},
    ), 201


# ── Private helpers ───────────────────────────────────────────────────────────

def _create_booklet_for_user(user: User, data: dict) -> str | None:
    """دفترچه جدید برای عضو می‌سازد. در صورت تکراری بودن کد دفترچه، پیام خطا برمی‌گرداند (None یعنی موفق)."""
    pid_int     = int(data["project_id"])
    last_serial = db_session.query(func.max(Booklet.serial)).filter_by(project_id=pid_int).scalar() or 0
    new_serial  = last_serial + 1
    c_no        = data.get("contract_no", "")
    code        = _booklet_code(c_no, pid_int, new_serial)

    dup = db_session.query(Booklet).filter_by(project_id=pid_int, code=code, deleted_at=None).first()
    if dup:
        owner_name = f"{dup.owner.first_name} {dup.owner.last_name}".strip() if dup.owner else "؟"
        return (f"کد دفترچه «{code}» قبلاً برای دفترچه دیگری در همین پروژه ثبت شده "
                f"(عضو: {owner_name}) — شماره قرارداد دیگری وارد کنید یا آن دفترچه را حذف کنید.")

    stale = db_session.query(Booklet).filter(
        Booklet.project_id == pid_int, Booklet.code == code, Booklet.deleted_at.isnot(None)
    ).first()
    if stale:
        stale.code = f"DEL{stale.id}-{stale.code}"[:30]

    booklet = Booklet(
        code=code,
        serial=new_serial,
        booklet_number=data.get("booklet_number", ""),
        project_id=pid_int,
        owner_id=user.id,
        share_type=data.get("share_type", "full"),
        contract_no=c_no,
        contract_date=data.get("contract_date", ""),
        contract_amount=parse_int(data.get("contract_amount")),
    )
    db_session.add(booklet)
    return None


def _cascade_delete_user(u: User) -> None:
    """همه رکوردهای وابسته به کاربر را قبل از حذف پاک یا nullify می‌کند."""
    from ...models import MemberDocument
    for d in db_session.query(MemberDocument).filter_by(user_id=u.id).all():
        db_session.delete(d)
    for d in db_session.query(MemberDocument).filter_by(uploaded_by=u.id).all():
        d.uploaded_by = None
    for n in db_session.query(Notification).filter_by(user_id=u.id).all():
        db_session.delete(n)
    for p in db_session.query(Payment).filter_by(user_id=u.id).all():
        db_session.delete(p)
    # شامل دفترچه‌های soft-delete شده — رابطه u.booklets آن‌ها را فیلتر می‌کند
    for b in db_session.query(Booklet).filter_by(owner_id=u.id).all():
        for tr in db_session.query(TransferRequest).filter_by(booklet_id=b.id).all():
            db_session.delete(tr)
        for th in db_session.query(TransferHistory).filter_by(booklet_id=b.id).all():
            db_session.delete(th)
        for pay in db_session.query(Payment).filter_by(booklet_id=b.id).all():
            pay.booklet_id = None
        db_session.delete(b)
    for tr in db_session.query(TransferRequest).filter_by(requester_id=u.id).all():
        db_session.delete(tr)
    for th in db_session.query(TransferHistory).filter(
        (TransferHistory.from_user_id == u.id) | (TransferHistory.to_user_id == u.id)
    ).all():
        db_session.delete(th)
    for t in db_session.query(Ticket).filter_by(creator_id=u.id).all():
        t.creator_id = None
    for a in db_session.query(Announcement).filter_by(author_id=u.id).all():
        a.author_id = None


def _excel_column_definitions():
    return [
        ("نام *",             "first_name",      18, True),
        ("نام خانوادگی *",   "last_name",       22, True),
        ("نام کاربری *",     "username",        20, True),
        ("رمز عبور *",       "password",        16, True),
        ("کد ملی",           "national_code",   14, False),
        ("جنسیت",            "gender",          10, False),
        ("شماره شناسنامه",   "id_number",       16, False),
        ("موبایل",           "phone",           14, False),
        ("تلفن اضطراری",     "emergency_phone", 16, False),
        ("نام پدر",          "father_name",     16, False),
        ("تاریخ تولد",       "birth_date",      14, False),
        ("محل تولد",         "birth_place",     16, False),
        ("وضعیت تاهل",       "marital_status",  14, False),
        ("تلفن ثابت",        "landline",        14, False),
        ("آدرس",             "address",         30, False),
        ("کد پستی",          "postal_code",     12, False),
        ("شغل",              "occupation",      16, False),
        ("ایمیل",            "email",           22, False),
        ("نام بانک",         "bank_name",       16, False),
        ("شماره حساب",       "account_number",  20, False),
        ("شماره شبا",        "iban",            26, False),
        ("نام پروژه",        "project_name",    22, False),
        ("نوع سهم",          "share_type",      14, False),
        ("شماره دفترچه",     "booklet_number",  18, False),
        ("شماره قرارداد",    "contract_no",     18, False),
        ("تاریخ قرارداد",    "contract_date",   14, False),
        ("مبلغ قرارداد",     "contract_amount", 16, False),
    ]


def _build_excel_header(ws, cols):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    NAVY = PatternFill("solid", fgColor="0E1B32")
    REQ  = PatternFill("solid", fgColor="1A3060")
    OPT  = PatternFill("solid", fgColor="2C4A7C")
    thin = Side(style="thin", color="C8A456")
    bdr  = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
    c = ws.cell(row=1, column=1, value="هیئت امنای مسکن دادگستری زنجان — فرم ورود اطلاعات اعضا")
    c.font = Font(bold=True, color="C8A456", size=13, name="Calibri")
    c.fill = NAVY
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True, readingOrder=2)
    ws.row_dimensions[1].height = 30

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(cols))
    c = ws.cell(row=2, column=1,
        value="ستون‌های دارای * اجباری هستند  |  ردیف سوم نمونه است — حذف کنید  |  تاریخ: YYYY/MM/DD  |  شبا بدون IR")
    c.font = Font(italic=True, color="FFFFFF", size=10, name="Calibri")
    c.fill = PatternFill("solid", fgColor="3A5A9B")
    c.alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
    ws.row_dimensions[2].height = 20

    for ci, (label, _, width, required) in enumerate(cols, start=1):
        cell = ws.cell(row=3, column=ci, value=label)
        cell.font      = Font(bold=True, color="FFFFFF", size=11, name="Calibri")
        cell.fill      = REQ if required else OPT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True, readingOrder=2)
        cell.border    = bdr
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.row_dimensions[3].height = 28


def _build_excel_example_row(ws, cols, project_names):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    EX_FILL = PatternFill("solid", fgColor="F0F4FA")
    EXAMPLE = [
        "علی", "احمدی", "ali.ahmadi", "Pass1234",
        "0123456789", "مرد", "123456",
        "09121234567", "09129999999",
        "حسین", "1360/05/15", "تهران",
        "متاهل", "02112345678", "تهران، خیابان ولیعصر",
        "1234567890", "مهندس", "ali@example.com",
        "ملی", "0123456789012", "123456789012345678901",
        project_names[0] if project_names else "", "تمام‌سهم", "د-۰۰۱",
        "CTR-1403-001", "1403/01/15", "500000000",
    ]
    thin = Side(style="thin", color="DDDDDD")
    bdr  = Border(left=thin, right=thin, top=thin, bottom=thin)
    for ci, val in enumerate(EXAMPLE, start=1):
        cell = ws.cell(row=4, column=ci, value=val)
        cell.fill      = EX_FILL
        cell.font      = Font(color="888888", size=10, name="Calibri", italic=True)
        cell.alignment = Alignment(horizontal="right", readingOrder=2)
        cell.border    = bdr
    ws.row_dimensions[4].height = 22


def _add_excel_validations(ws, wb, cols, project_names):
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    def _col_letter(key):
        for ci, (_, k, *_rest) in enumerate(cols, start=1):
            if k == key:
                return get_column_letter(ci)
        return "A"

    dv_gender = DataValidation(type="list", formula1='"مرد,زن"', allow_blank=True, showDropDown=False)
    dv_gender.sqref = "F5:F2000"
    ws.add_data_validation(dv_gender)

    dv_marital = DataValidation(type="list", formula1='"مجرد,متاهل,مطلقه,بیوه"', allow_blank=True, showDropDown=False)
    dv_marital.sqref = "M5:M2000"
    ws.add_data_validation(dv_marital)

    share_col = _col_letter("share_type")
    dv_share = DataValidation(type="list", formula1='"تمام‌سهم,نیم‌سهم"', allow_blank=True, showDropDown=False)
    dv_share.sqref = f"{share_col}5:{share_col}2000"
    ws.add_data_validation(dv_share)

    if project_names:
        wp = wb.create_sheet("_پروژه‌ها")
        wp.sheet_state = "hidden"
        for i, pname in enumerate(project_names, start=1):
            wp.cell(row=i, column=1, value=pname)
        proj_col = _col_letter("project_name")
        dv_proj = DataValidation(
            type="list",
            formula1=f"'_پروژه‌ها'!$A$1:$A${len(project_names)}",
            allow_blank=True, showDropDown=False,
        )
        dv_proj.sqref = f"{proj_col}5:{proj_col}2000"
        ws.add_data_validation(dv_proj)


def _build_excel_guide_sheet(wb, cols):
    from openpyxl.styles import Alignment, Font, PatternFill
    wg = wb.create_sheet("راهنما")
    wg.sheet_view.rightToLeft = True
    wg.column_dimensions["A"].width = 20
    wg.column_dimensions["B"].width = 16
    wg.column_dimensions["C"].width = 50

    GUIDE_ROWS = [
        ("عنوان راهنما", "اجباری", "توضیحات"),
        ("نام", "بله", "نام کوچک عضو"),
        ("نام خانوادگی", "بله", "نام خانوادگی عضو"),
        ("نام کاربری", "بله", "منحصربه‌فرد — برای ورود به سامانه"),
        ("رمز عبور", "بله", "حداقل ۴ کاراکتر"),
        ("کد ملی", "خیر", "۱۰ رقم بدون خط تیره"),
        ("موبایل", "خیر", "مثال: 09121234567"),
        ("تلفن اضطراری", "خیر", "شماره تماس اضطراری"),
        ("نام پدر", "خیر", "نام پدر عضو"),
        ("تاریخ تولد", "خیر", "فرمت: YYYY/MM/DD"),
        ("محل تولد", "خیر", "شهر یا استان"),
        ("وضعیت تاهل", "خیر", "مجرد / متاهل / مطلقه / بیوه"),
        ("تلفن ثابت", "خیر", "مثال: 02112345678"),
        ("آدرس", "خیر", "آدرس کامل محل سکونت"),
        ("کد پستی", "خیر", "۱۰ رقم"),
        ("شغل", "خیر", "عنوان شغلی"),
        ("ایمیل", "خیر", "آدرس ایمیل"),
        ("نام بانک", "خیر", "مثال: ملی، صادرات، پاسارگاد"),
        ("شماره حساب", "خیر", "شماره حساب بانکی"),
        ("شماره شبا", "خیر", "۲۲ رقم بدون IR"),
        ("نام پروژه", "خیر", "دقیقاً با نام پروژه فعال مطابقت داشته باشد"),
        ("نوع سهم", "خیر", "تمام‌سهم یا نیم‌سهم — پیش‌فرض: تمام‌سهم"),
        ("شماره دفترچه", "خیر", "شماره دستی دفترچه (اختیاری)"),
        ("شماره قرارداد", "خیر", "اگر وارد شود به‌عنوان کد دفترچه استفاده می‌شود"),
        ("تاریخ قرارداد", "خیر", "فرمت: YYYY/MM/DD"),
        ("مبلغ قرارداد", "خیر", "مبلغ به ریال — فقط عدد"),
    ]
    NAVY = PatternFill("solid", fgColor="0E1B32")
    ROW1 = PatternFill("solid", fgColor="F0F4FA")
    ROW2 = PatternFill("solid", fgColor="FFFFFF")

    for ri, row_data in enumerate(GUIDE_ROWS, start=1):
        fill = NAVY if ri == 1 else (ROW1 if ri % 2 == 0 else ROW2)
        fnt  = Font(bold=(ri == 1), color=("C8A456" if ri == 1 else "000000"), size=11, name="Calibri")
        for ci, val in enumerate(row_data, start=1):
            cell = wg.cell(row=ri, column=ci, value=val)
            cell.fill      = fill
            cell.font      = fnt
            cell.alignment = Alignment(
                horizontal=("center" if ci < 3 else "right"),
                vertical="center", wrap_text=True, readingOrder=2,
            )
        wg.row_dimensions[ri].height = 22 if ri > 1 else 28

    note_row = len(GUIDE_ROWS) + 2
    wg.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=3)
    note = wg.cell(row=note_row, column=1, value="نکته: ردیف نمونه (ردیف ۴) در شیت اعضا را قبل از ارسال حذف کنید.")
    note.font      = Font(bold=True, color="C8A456", size=11, name="Calibri")
    note.fill      = NAVY
    note.alignment = Alignment(horizontal="center", readingOrder=2)
    wg.row_dimensions[note_row].height = 26


def _find_excel_header(ws):
    for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
        row_text = [str(c or "").strip() for c in row]
        if any("نام کاربری" in t for t in row_text):
            return row_text
    return None


def _build_column_index(header_row: list) -> dict:
    COL_MAP = {
        "نام": "first_name", "نام خانوادگی": "last_name",
        "نام کاربری": "username", "رمز عبور": "password",
        "کد ملی": "national_code", "جنسیت": "gender",
        "شماره شناسنامه": "id_number", "موبایل": "phone",
        "تلفن اضطراری": "emergency_phone", "نام پدر": "father_name",
        "تاریخ تولد": "birth_date", "محل تولد": "birth_place",
        "وضعیت تاهل": "marital_status", "تلفن ثابت": "landline",
        "آدرس": "address", "کد پستی": "postal_code",
        "شغل": "occupation", "ایمیل": "email",
        "نام بانک": "bank_name", "شماره حساب": "account_number",
        "شماره شبا": "iban", "نام پروژه": "project_name",
        "نوع سهم": "share_type", "شماره دفترچه": "booklet_number",
        "شماره قرارداد": "contract_no", "تاریخ قرارداد": "contract_date",
        "مبلغ قرارداد": "contract_amount",
    }
    index = {}
    for label, field in COL_MAP.items():
        for i, h in enumerate(header_row):
            if label in h:
                index[field] = i
                break
    return index


def _import_single_row(row_num, row_vals, col_idx, created, skipped, errors):
    def _v(field):
        idx = col_idx.get(field)
        return row_vals[idx] if idx is not None and idx < len(row_vals) else ""

    first_name = _v("first_name")
    username   = _v("username")
    if not first_name or not username:
        return "skip"
    if username == "ali.ahmadi":
        return "skip"

    last_name = _v("last_name")
    password  = _v("password")
    if not last_name or not password:
        errors.append({"row": row_num, "username": username, "error": "نام خانوادگی یا رمز عبور خالی است."})
        return "skip"

    field_data = {f: _v(f) for f, *_ in
                  [("national_code",), ("phone",), ("emergency_phone",), ("landline",),
                   ("postal_code",), ("id_number",), ("account_number",), ("iban",),
                   ("first_name",), ("last_name",), ("gender",), ("father_name",),
                   ("birth_date",), ("birth_place",), ("marital_status",),
                   ("occupation",), ("email",), ("bank_name",)]}
    v_err = validate_user_fields(field_data)
    if v_err:
        errors.append({"row": row_num, "username": username, "error": v_err})
        return "skip"

    if db_session.query(User).filter_by(username=username).first():
        skipped.append({"row": row_num, "username": username, "reason": "نام کاربری تکراری است."})
        return "skip"

    nat_code = field_data.get("national_code")
    if nat_code and db_session.query(User).filter_by(national_code=nat_code).first():
        skipped.append({"row": row_num, "username": username, "reason": f"کد ملی {nat_code} تکراری است."})
        return "skip"

    fd = field_data  # مقادیر نرمال‌شده (ارقام فارسی → انگلیسی)
    u = User(
        username=username,
        password_hash=generate_password_hash(password),
        role="member",
        first_name=first_name,
        last_name=last_name,
        national_code=fd.get("national_code") or None,
        gender=fd.get("gender") or None,
        id_number=fd.get("id_number") or None,
        phone=fd.get("phone") or None,
        emergency_phone=fd.get("emergency_phone") or None,
        father_name=fd.get("father_name") or None,
        birth_date=fd.get("birth_date") or None,
        birth_place=fd.get("birth_place") or None,
        marital_status=fd.get("marital_status") or None,
        landline=fd.get("landline") or None,
        address=_v("address") or None,
        postal_code=fd.get("postal_code") or None,
        occupation=fd.get("occupation") or None,
        email=fd.get("email") or None,
        bank_name=fd.get("bank_name") or None,
        account_number=fd.get("account_number") or None,
        iban=fd.get("iban") or None,
        active=True,
        profile_complete=True,
    )
    db_session.add(u)
    db_session.flush()

    project_name = _v("project_name")
    if project_name:
        from sqlalchemy import func as _func
        proj = db_session.query(Project).filter(
            _func.lower(Project.name) == project_name.lower()
        ).first()
        if not proj:
            errors.append({"row": row_num, "username": username,
                           "error": f"پروژه «{project_name}» یافت نشد — عضو ساخته شد اما بدون دفترچه."})
        else:
            share_label = _v("share_type")
            share_type  = "half" if "نیم" in share_label else "full"
            last_serial = db_session.query(func.max(Booklet.serial)).filter_by(project_id=proj.id).scalar() or 0
            xls_cno     = _v("contract_no") or ""
            try:
                xls_camount = int(float((_v("contract_amount") or "0").replace(",", "")))
            except (ValueError, AttributeError):
                xls_camount = 0
            xls_code = _booklet_code(xls_cno, proj.id, last_serial + 1)
            xls_dup = db_session.query(Booklet).filter_by(project_id=proj.id, code=xls_code, deleted_at=None).first()
            if xls_dup:
                dup_owner = f"{xls_dup.owner.first_name} {xls_dup.owner.last_name}".strip() if xls_dup.owner else "؟"
                errors.append({"row": row_num, "username": username,
                               "error": f"کد دفترچه «{xls_code}» در همین پروژه تکراری است (عضو: {dup_owner}) — عضو ساخته شد اما بدون دفترچه."})
            else:
                xls_stale = db_session.query(Booklet).filter(
                    Booklet.project_id == proj.id, Booklet.code == xls_code, Booklet.deleted_at.isnot(None)
                ).first()
                if xls_stale:
                    xls_stale.code = f"DEL{xls_stale.id}-{xls_stale.code}"[:30]
                db_session.add(Booklet(
                    code=xls_code,
                    serial=last_serial + 1,
                    booklet_number=_v("booklet_number") or "",
                    contract_no=xls_cno,
                    contract_date=_v("contract_date") or "",
                    contract_amount=xls_camount,
                    project_id=proj.id,
                    owner_id=u.id,
                    share_type=share_type,
                ))

    created.append({"row": row_num, "username": username, "name": f"{first_name} {last_name}"})
    return "ok"
