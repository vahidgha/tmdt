"""Dashboard page routes for the Form Builder module."""
from flask import Blueprint, render_template, abort, redirect, url_for
from flask_login import login_required, current_user
from .. import db_session
from ..models import Form, FormSubmission, SiteSetting


def _settings():
    return {r.key: r.value for r in db_session.query(SiteSetting).all()}


def _render(template, **ctx):
    return render_template(template, user=current_user, site_settings=_settings(), **ctx)

bp = Blueprint('forms_dash', __name__)


def _admin():
    if current_user.role != 'admin':
        abort(403)


@bp.get('/forms')
@login_required
def forms_list():
    _admin()
    forms = db_session.query(Form).order_by(Form.created_at.desc()).all()
    return _render('dashboard/forms.html', forms=forms)


@bp.get('/forms/<int:fid>/builder')
@login_required
def forms_builder(fid):
    _admin()
    form = db_session.get(Form, fid)
    if not form:
        abort(404)
    return _render('dashboard/forms_builder.html', form=form)


@bp.get('/forms/<int:fid>/submissions')
@login_required
def forms_submissions(fid):
    _admin()
    form = db_session.get(Form, fid)
    if not form:
        abort(404)
    return _render('dashboard/forms_submissions.html', form=form)


@bp.get('/forms/public/<slug>')
def public_form_page(slug):
    form = db_session.query(Form).filter_by(slug=slug, status='published').first()
    if not form:
        abort(404)
    return render_template('forms/render.html', form=form)


@bp.get('/forms/mine')
@login_required
def forms_mine():
    """فهرست فرم‌های در دسترس عضو — چه عمومی چه مخصوص اعضا (اختصاصی)."""
    if current_user.role == 'admin':
        return redirect(url_for('forms_dash.forms_list'))
    return _render('dashboard/forms_mine.html')
