"""REST API for the Form Builder module."""
import json, re, secrets
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, current_app, send_file
from flask_login import current_user
from sqlalchemy import or_
from .. import db_session
from ..models import (Form, FormStep, FormField, FormSubmission, FormSubmissionValue,
                      FormSubmissionHistory, FormAllowedPerson)
from ..utils.validation import normalize_digits

bp = Blueprint('forms_api', __name__)


# ── helpers ──────────────────────────────────────────────────────────────────
def _body():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


def _admin_required(fn):
    """Require authenticated admin; returns JSON 401/403 (never redirects)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify(error='احراز هویت الزامی است'), 401
        if current_user.role != 'admin':
            return jsonify(error='دسترسی ممنوع'), 403
        return fn(*args, **kwargs)
    return wrapper


def _login_required_json(fn):
    """Like @_login_required_json but returns JSON 401 instead of redirecting."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify(error='احراز هویت الزامی است'), 401
        return fn(*args, **kwargs)
    return wrapper


def _slugify(text):
    slug = re.sub(r'[^\w\s-]', '', text.lower()).strip()
    slug = re.sub(r'[\s_-]+', '-', slug)
    return slug or secrets.token_hex(4)


def _ensure_unique_slug(slug, exclude_id=None):
    base, i = slug, 1
    while True:
        q = db_session.query(Form).filter_by(slug=slug)
        if exclude_id:
            q = q.filter(Form.id != exclude_id)
        if not q.first():
            return slug
        slug = f"{base}-{i}"
        i += 1


# ── Forms CRUD ────────────────────────────────────────────────────────────────
@bp.get('/forms')
@_login_required_json
def list_forms():
    q = db_session.query(Form)
    if current_user.role != 'admin':
        # کاربر واردشده — چه فرم عمومی چه فرم مخصوص اعضا (is_public=False)،
        # هر دو باید در فهرست او دیده شوند؛ فقط پیش‌نویس/بایگانی مخفی می‌ماند
        q = q.filter(Form.status == 'published')
    forms = q.order_by(Form.created_at.desc()).all()
    return jsonify(forms=[f.to_dict() for f in forms])


@bp.post('/forms')
@_admin_required
def create_form():
    data  = _body()
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify(error='عنوان فرم الزامی است'), 400

    slug = _ensure_unique_slug(_slugify(data.get('slug') or title))
    form = Form(
        title           = title,
        description     = data.get('description', ''),
        slug            = slug,
        status          = data.get('status', 'draft'),
        is_public       = bool(data.get('is_public', True)),
        multi_step      = bool(data.get('multi_step', False)),
        allow_edit      = bool(data.get('allow_edit', False)),
        max_submissions = int(data.get('max_submissions') or 0),
        success_msg     = data.get('success_msg', ''),
        restrict_access = bool(data.get('restrict_access', False)),
        created_by      = current_user.id,
    )
    db_session.add(form)
    db_session.flush()

    # create first default step
    step = FormStep(form_id=form.id, title='مرحله ۱', order=0)
    db_session.add(step)
    db_session.commit()
    return jsonify(form=form.to_dict()), 201


@bp.get('/forms/<int:fid>')
@_login_required_json
def get_form(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    if current_user.role != 'admin' and (form.status != 'published' or not form.is_public):
        return jsonify(error='دسترسی ممنوع'), 403
    d = form.to_dict()
    d['steps'] = [s.to_dict() for s in form.steps]
    return jsonify(form=d)


@bp.put('/forms/<int:fid>')
@_admin_required
def update_form(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    data = _body()
    for k in ('title', 'description', 'status', 'success_msg'):
        if k in data:
            setattr(form, k, data[k])
    for k in ('is_public', 'multi_step', 'allow_edit', 'restrict_access'):
        if k in data:
            setattr(form, k, bool(data[k]))
    if 'max_submissions' in data:
        form.max_submissions = int(data['max_submissions'] or 0)
    if 'slug' in data and data['slug']:
        form.slug = _ensure_unique_slug(_slugify(data['slug']), exclude_id=fid)
    form.updated_at = datetime.utcnow()
    db_session.commit()
    return jsonify(form=form.to_dict())


@bp.delete('/forms/<int:fid>')
@_admin_required
def delete_form(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    db_session.delete(form)
    db_session.commit()
    return jsonify(ok=True)


# ── Steps ─────────────────────────────────────────────────────────────────────
@bp.post('/forms/<int:fid>/steps')
@_admin_required
def add_step(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    data  = _body()
    order = len(form.steps)
    step  = FormStep(
        form_id     = fid,
        title       = data.get('title', f'مرحله {order + 1}'),
        description = data.get('description', ''),
        order       = order,
    )
    db_session.add(step)
    db_session.commit()
    return jsonify(step=step.to_dict()), 201


@bp.put('/forms/<int:fid>/steps/<int:sid>')
@_admin_required
def update_step(fid, sid):
    step = db_session.query(FormStep).filter_by(id=sid, form_id=fid).first()
    if not step:
        return jsonify(error='یافت نشد'), 404
    data = _body()
    for k in ('title', 'description', 'order'):
        if k in data:
            setattr(step, k, data[k])
    db_session.commit()
    return jsonify(step=step.to_dict())


@bp.delete('/forms/<int:fid>/steps/<int:sid>')
@_admin_required
def delete_step(fid, sid):
    step = db_session.query(FormStep).filter_by(id=sid, form_id=fid).first()
    if not step:
        return jsonify(error='یافت نشد'), 404
    db_session.delete(step)
    db_session.commit()
    return jsonify(ok=True)


# ── Fields ────────────────────────────────────────────────────────────────────
VALID_TYPES = {
    'text', 'textarea', 'number', 'email', 'tel', 'url', 'password',
    'date', 'time', 'datetime', 'date_range',
    'select', 'multi_select', 'radio', 'checkbox', 'toggle',
    'file', 'image', 'signature',
    'rating', 'slider', 'color',
    'section', 'divider', 'html',
    'map', 'address',
    'national_code', 'phone_ir', 'iban',
}


@bp.post('/forms/<int:fid>/fields')
@_admin_required
def add_field(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    data = _body()
    step_id = data.get('step_id')
    if not step_id:
        # use first step
        if not form.steps:
            return jsonify(error='هیچ مرحله‌ای وجود ندارد'), 400
        step_id = form.steps[0].id

    step = db_session.query(FormStep).filter_by(id=step_id, form_id=fid).first()
    if not step:
        return jsonify(error='مرحله یافت نشد'), 404

    ftype = data.get('field_type', 'text')
    if ftype not in VALID_TYPES:
        return jsonify(error='نوع فیلد نامعتبر است'), 400

    opts = data.get('options')
    cond = data.get('conditions')
    vali = data.get('validation')

    field = FormField(
        step_id     = step_id,
        form_id     = fid,
        field_type  = ftype,
        label       = data.get('label', 'فیلد جدید'),
        placeholder = data.get('placeholder', ''),
        help_text   = data.get('help_text', ''),
        required    = bool(data.get('required', False)),
        options     = json.dumps(opts, ensure_ascii=False) if opts else None,
        validation  = json.dumps(vali, ensure_ascii=False) if vali else None,
        conditions  = json.dumps(cond, ensure_ascii=False) if cond else None,
        default_val = data.get('default_val', ''),
        order       = int(data.get('order', len(step.fields))),
        width       = data.get('width', 'full'),
    )
    db_session.add(field)
    db_session.commit()
    return jsonify(field=field.to_dict()), 201


@bp.put('/forms/<int:fid>/fields/<int:field_id>')
@_admin_required
def update_field(fid, field_id):
    field = db_session.query(FormField).filter_by(id=field_id, form_id=fid).first()
    if not field:
        return jsonify(error='فیلد یافت نشد'), 404
    data = _body()
    for k in ('label', 'placeholder', 'help_text', 'default_val', 'width', 'order', 'field_type'):
        if k in data:
            setattr(field, k, data[k])
    if 'required' in data:
        field.required = bool(data['required'])
    for k in ('options', 'validation', 'conditions'):
        if k in data:
            v = data[k]
            setattr(field, k, json.dumps(v, ensure_ascii=False) if v else None)
    db_session.commit()
    return jsonify(field=field.to_dict())


@bp.delete('/forms/<int:fid>/fields/<int:field_id>')
@_admin_required
def delete_field(fid, field_id):
    field = db_session.query(FormField).filter_by(id=field_id, form_id=fid).first()
    if not field:
        return jsonify(error='فیلد یافت نشد'), 404
    db_session.delete(field)
    db_session.commit()
    return jsonify(ok=True)


@bp.post('/forms/<int:fid>/fields/reorder')
@_admin_required
def reorder_fields(fid):
    """Accepts {fields: [{id, order, step_id}, ...]} and batch-updates order."""
    data   = _body()
    items  = data.get('fields', [])
    for item in items:
        field = db_session.query(FormField).filter_by(id=item['id'], form_id=fid).first()
        if field:
            field.order   = item.get('order', field.order)
            field.step_id = item.get('step_id', field.step_id)
    db_session.commit()
    return jsonify(ok=True)


# ── Allowed people (فرم اختصاصی) ───────────────────────────────────────────────
@bp.get('/forms/<int:fid>/allowed')
@_admin_required
def list_allowed_people(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    people = db_session.query(FormAllowedPerson).filter_by(form_id=fid)\
                       .order_by(FormAllowedPerson.created_at.desc()).all()
    return jsonify(people=[p.to_dict() for p in people])


@bp.post('/forms/<int:fid>/allowed')
@_admin_required
def add_allowed_person(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    data          = _body()
    national_code = normalize_digits((data.get('national_code') or '').strip())
    phone         = normalize_digits((data.get('phone') or '').strip())
    if not national_code and not phone:
        return jsonify(error='حداقل کد ملی یا موبایل را وارد کنید'), 400
    person = FormAllowedPerson(
        form_id       = fid,
        national_code = national_code,
        phone         = phone,
        full_name     = (data.get('full_name') or '').strip(),
    )
    db_session.add(person)
    db_session.commit()
    return jsonify(person=person.to_dict()), 201


@bp.delete('/forms/<int:fid>/allowed/<int:pid>')
@_admin_required
def delete_allowed_person(fid, pid):
    person = db_session.query(FormAllowedPerson).filter_by(id=pid, form_id=fid).first()
    if not person:
        return jsonify(error='یافت نشد'), 404
    db_session.delete(person)
    db_session.commit()
    return jsonify(ok=True)


@bp.get('/forms/allowed/template')
@_admin_required
def allowed_people_template():
    """دانلود فایل اکسل نمونه برای معرفی لیست افراد مجاز یک فرم اختصاصی"""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "افراد مجاز"
    ws.sheet_view.rightToLeft = True

    NAVY    = PatternFill("solid", fgColor="0E1B32")
    EX_FILL = PatternFill("solid", fgColor="F0F4FA")
    cols = [("نام و نام‌خانوادگی", 26), ("کد ملی", 16), ("موبایل", 16)]

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
    c = ws.cell(row=1, column=1, value="لیست افراد مجاز به تکمیل فرم — حداقل یکی از کد ملی یا موبایل الزامی است")
    c.font = Font(bold=True, color="C8A456", size=12, name="Calibri")
    c.fill = NAVY
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True, readingOrder=2)
    ws.row_dimensions[1].height = 28

    for ci, (label, width) in enumerate(cols, start=1):
        cell = ws.cell(row=2, column=ci, value=label)
        cell.font = Font(bold=True, color="FFFFFF", size=11, name="Calibri")
        cell.fill = PatternFill("solid", fgColor="1A3060")
        cell.alignment = Alignment(horizontal="center", vertical="center", readingOrder=2)
        ws.column_dimensions[get_column_letter(ci)].width = width

    example = ["علی احمدی", "0123456789", "09121234567"]
    for ci, val in enumerate(example, start=1):
        cell = ws.cell(row=3, column=ci, value=val)
        cell.fill = EX_FILL
        cell.font = Font(color="888888", size=10, name="Calibri", italic=True)
        cell.alignment = Alignment(horizontal="right", readingOrder=2)
    ws.row_dimensions[3].height = 22
    ws.freeze_panes = "A3"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="form_allowed_people_template.xlsx",
    )


@bp.post('/forms/<int:fid>/allowed/import')
@_admin_required
def import_allowed_people(fid):
    """ورود انبوه افراد مجاز از فایل اکسل"""
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404

    if 'file' not in request.files:
        return jsonify(error='فایل انتخاب نشده.'), 400
    f = request.files['file']
    if not f.filename.endswith(('.xlsx', '.xls')):
        return jsonify(error='فرمت فایل باید xlsx باشد.'), 400

    from openpyxl import load_workbook
    try:
        wb = load_workbook(filename=f, read_only=True, data_only=True)
    except Exception:
        return jsonify(error='فایل اکسل معتبر نیست.'), 400

    ws = wb.active
    created, skipped = [], []
    for row_num, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row_num <= 2:
            continue  # عنوان و هدر
        vals          = [str(c or '').strip() for c in row]
        full_name     = vals[0] if len(vals) > 0 else ''
        national_code = normalize_digits(vals[1]) if len(vals) > 1 else ''
        phone         = normalize_digits(vals[2]) if len(vals) > 2 else ''
        if not national_code and not phone:
            continue
        conds = []
        if national_code:
            conds.append(FormAllowedPerson.national_code == national_code)
        if phone:
            conds.append(FormAllowedPerson.phone == phone)
        exists = db_session.query(FormAllowedPerson).filter_by(form_id=fid)\
                           .filter(or_(*conds)).first()
        if exists:
            skipped.append({'row': row_num, 'national_code': national_code, 'phone': phone})
            continue
        db_session.add(FormAllowedPerson(
            form_id=fid, national_code=national_code, phone=phone, full_name=full_name,
        ))
        created.append({'row': row_num, 'full_name': full_name})

    db_session.commit()
    return jsonify(ok=True, created=len(created), skipped=len(skipped)), 201


def _find_allowed_person(form_id, national_code='', phone=''):
    """افراد مجاز فرم را بر اساس کد ملی یا موبایل (هرکدام که وارد شده) پیدا می‌کند."""
    national_code = normalize_digits((national_code or '').strip())
    phone         = normalize_digits((phone or '').strip())
    if not national_code and not phone:
        return None
    q = db_session.query(FormAllowedPerson).filter(FormAllowedPerson.form_id == form_id)
    conds = []
    if national_code:
        conds.append(FormAllowedPerson.national_code == national_code)
    if phone:
        conds.append(FormAllowedPerson.phone == phone)
    return q.filter(or_(*conds)).first()


# ── Public form by slug ───────────────────────────────────────────────────────
@bp.get('/public/forms/<slug>')
def public_form(slug):
    form = db_session.query(Form).filter_by(slug=slug, status='published').first()
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    if not form.is_public and not current_user.is_authenticated:
        return jsonify(error='برای پر کردن این فرم باید وارد شوید'), 401
    d = form.to_dict()
    d['steps'] = [s.to_dict() for s in form.steps]
    return jsonify(form=d)


@bp.post('/public/forms/<slug>/check-access')
def check_form_access(slug):
    """برای فرم‌های اختصاصی — پیش از نمایش فرم، کد ملی/موبایل کاربر را با لیست مجاز تطبیق می‌دهد."""
    form = db_session.query(Form).filter_by(slug=slug, status='published').first()
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    if not form.restrict_access:
        return jsonify(ok=True)
    data   = _body()
    person = _find_allowed_person(form.id, data.get('national_code', ''), data.get('phone', ''))
    if not person:
        return jsonify(error='شما در لیست افراد مجاز به تکمیل این فرم نیستید.'), 403
    return jsonify(ok=True)


# ── Submissions ───────────────────────────────────────────────────────────────
@bp.post('/public/forms/<slug>/submit')
def submit_form(slug):
    form = db_session.query(Form).filter_by(slug=slug, status='published').first()
    if not form:
        return jsonify(error='فرم یافت نشد'), 404

    if form.max_submissions:
        count = db_session.query(FormSubmission).filter_by(form_id=form.id).count()
        if count >= form.max_submissions:
            return jsonify(error='ظرفیت پاسخ‌دهی به این فرم تکمیل شده است'), 400

    if form.expires_at and datetime.utcnow() > form.expires_at:
        return jsonify(error='مهلت پاسخ‌دهی به این فرم منقضی شده است'), 400

    data = _body()

    allowed_person = None
    if form.restrict_access:
        allowed_person = _find_allowed_person(
            form.id, data.get('access_national_code', ''), data.get('access_phone', ''))
        if not allowed_person:
            return jsonify(error='شما در لیست افراد مجاز به تکمیل این فرم نیستید.'), 403

    sub  = FormSubmission(
        form_id      = form.id,
        submitter_id = current_user.id if current_user.is_authenticated else None,
        ip_address   = request.remote_addr,
        status       = 'submitted',
    )
    db_session.add(sub)
    db_session.flush()

    if allowed_person:
        allowed_person.used_at = datetime.utcnow()

    all_fields = db_session.query(FormField).filter_by(form_id=form.id).all()
    for field in all_fields:
        key = f'field_{field.id}'
        val = data.get(key, '')
        # validate required
        if field.required and not val:
            db_session.rollback()
            return jsonify(error=f'فیلد «{field.label}» الزامی است'), 400
        sv = FormSubmissionValue(
            submission_id = sub.id,
            field_id      = field.id,
            field_label   = field.label,
            value         = str(val) if val is not None else '',
        )
        db_session.add(sv)

    # history entry
    db_session.add(FormSubmissionHistory(
        submission_id = sub.id,
        actor_id      = current_user.id if current_user.is_authenticated else None,
        action        = 'submitted',
    ))
    db_session.commit()
    return jsonify(ok=True, submission_id=sub.id,
                   message=form.success_msg or 'فرم با موفقیت ثبت شد'), 201


@bp.get('/forms/<int:fid>/submissions')
@_admin_required
def list_submissions(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404
    page    = int(request.args.get('page', 1))
    per     = int(request.args.get('per', 20))
    status  = request.args.get('status')
    q       = db_session.query(FormSubmission).filter_by(form_id=fid)
    if status:
        q = q.filter_by(status=status)
    total = q.count()
    subs  = q.order_by(FormSubmission.created_at.desc()).offset((page-1)*per).limit(per).all()
    return jsonify(submissions=[s.to_dict() for s in subs], total=total, page=page, per=per)


@bp.get('/forms/<int:fid>/submissions/<int:sid>')
@_admin_required
def get_submission(fid, sid):
    sub = db_session.query(FormSubmission).filter_by(id=sid, form_id=fid).first()
    if not sub:
        return jsonify(error='یافت نشد'), 404
    d = sub.to_dict(with_values=True)
    d['history'] = [
        {'action': h.action, 'note': h.note,
         'actor': h.actor.full_name if h.actor else 'سیستم',
         'created_at': h.created_at.isoformat()}
        for h in sub.history
    ]
    return jsonify(submission=d)


@bp.put('/forms/<int:fid>/submissions/<int:sid>/status')
@_admin_required
def update_submission_status(fid, sid):
    sub = db_session.query(FormSubmission).filter_by(id=sid, form_id=fid).first()
    if not sub:
        return jsonify(error='یافت نشد'), 404
    data   = _body()
    status = data.get('status')
    if status not in ('submitted', 'reviewing', 'approved', 'rejected'):
        return jsonify(error='وضعیت نامعتبر'), 400
    sub.status     = status
    sub.note       = data.get('note', sub.note)
    sub.updated_at = datetime.utcnow()
    db_session.add(FormSubmissionHistory(
        submission_id = sub.id,
        actor_id      = current_user.id,
        action        = status,
        note          = data.get('note', ''),
    ))
    db_session.commit()
    return jsonify(ok=True)


@bp.delete('/forms/<int:fid>/submissions/<int:sid>')
@_admin_required
def delete_submission(fid, sid):
    sub = db_session.query(FormSubmission).filter_by(id=sid, form_id=fid).first()
    if not sub:
        return jsonify(error='یافت نشد'), 404
    db_session.delete(sub)
    db_session.commit()
    return jsonify(ok=True)


# ── Export ────────────────────────────────────────────────────────────────────
@bp.get('/forms/<int:fid>/export')
@_admin_required
def export_submissions(fid):
    import io
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return jsonify(error='openpyxl نصب نیست'), 500

    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404

    all_fields = db_session.query(FormField).filter_by(form_id=fid).order_by(FormField.order).all()
    subs = db_session.query(FormSubmission).filter_by(form_id=fid)\
                     .order_by(FormSubmission.created_at.desc()).all()

    wb  = Workbook()
    ws  = wb.active
    ws.title = 'پاسخ‌ها'
    ws.sheet_view.rightToLeft = True

    hdr_fill = PatternFill('solid', fgColor='0E1B32')
    hdr_font = Font(bold=True, color='C8A456', size=11)
    hdr_cols = ['#', 'فرستنده', 'وضعیت', 'تاریخ ثبت'] + [f.label for f in all_fields]

    for ci, col in enumerate(hdr_cols, 1):
        cell = ws.cell(row=1, column=ci, value=col)
        cell.font      = hdr_font
        cell.fill      = hdr_fill
        cell.alignment = Alignment(horizontal='center')

    status_map = {
        'submitted': 'ثبت شده', 'reviewing': 'در بررسی',
        'approved': 'تأیید شده', 'rejected': 'رد شده',
    }
    for ri, sub in enumerate(subs, 2):
        val_map = {v.field_id: v.value for v in sub.values}
        ws.cell(row=ri, column=1, value=ri-1)
        ws.cell(row=ri, column=2, value=sub.submitter.full_name if sub.submitter else 'ناشناس')
        ws.cell(row=ri, column=3, value=status_map.get(sub.status, sub.status))
        ws.cell(row=ri, column=4, value=sub.created_at.strftime('%Y-%m-%d %H:%M'))
        for ci, field in enumerate(all_fields, 5):
            ws.cell(row=ri, column=ci, value=val_map.get(field.id, ''))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"form_{fid}_submissions.xlsx"
    return send_file(buf, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ── Analytics ─────────────────────────────────────────────────────────────────
@bp.get('/forms/<int:fid>/analytics')
@_admin_required
def form_analytics(fid):
    form = db_session.get(Form, fid)
    if not form:
        return jsonify(error='فرم یافت نشد'), 404

    subs  = db_session.query(FormSubmission).filter_by(form_id=fid).all()
    total = len(subs)
    by_status = {}
    for s in subs:
        by_status[s.status] = by_status.get(s.status, 0) + 1

    # daily counts (last 30 days)
    from collections import defaultdict
    daily = defaultdict(int)
    for s in subs:
        day = s.created_at.strftime('%Y-%m-%d')
        daily[day] += 1

    return jsonify(
        total       = total,
        by_status   = by_status,
        daily       = dict(sorted(daily.items())[-30:]),
        field_count = db_session.query(FormField).filter_by(form_id=fid).count(),
        step_count  = db_session.query(FormStep).filter_by(form_id=fid).count(),
    )
