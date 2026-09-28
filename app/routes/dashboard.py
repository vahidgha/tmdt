"""مسیرهای رندر صفحات پنل (dashboard) — فقط رندر قالب‌های HTML؛ داده‌ها از app/routes/api/ گرفته می‌شوند."""
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from .. import db_session
from ..models import SiteSetting

bp = Blueprint("dashboard", __name__)


def _settings():
    return {r.key: r.value for r in db_session.query(SiteSetting).all()}


def _render(template, **ctx):
    return render_template(f"dashboard/{template}", user=current_user,
                           site_settings=_settings(), **ctx)


@bp.before_request
@login_required
def _auth():
    pass


@bp.route("/")
def home():
    if current_user.role == "finance":
        return redirect(url_for("dashboard.accounting"))
    if current_user.role == "member" and not current_user.is_profile_complete():
        return _render("complete_profile.html")
    return _render("home.html")


@bp.route("/help")
def help_page():
    """راهنمای استفاده از سامانه — محتوا بر اساس نقش کاربر فیلتر می‌شود."""
    return _render("help.html")

@bp.route("/members")
def members():        return _render("members.html")

@bp.route("/projects")
def projects():       return _render("projects.html")

@bp.route("/contract/<int:booklet_id>")
def contract(booklet_id): return _render("contract.html", booklet_id=booklet_id)

@bp.route("/announcements")
def announcements():  return _render("announcements.html")

@bp.route("/requests")
def requests():       return _render("requests.html")

@bp.route("/requests/<int:rid>")
def request_detail(rid): return _render("request_detail.html", request_id=rid)

@bp.route("/history")
def history():        return _render("history.html")

@bp.route("/finance")
def finance():        return _render("finance.html")

@bp.route("/accounting")
def accounting():
    if current_user.role not in ('admin', 'finance'):
        return redirect(url_for('dashboard.home'))
    return _render("accounting.html")

@bp.route("/accounting/statement/<int:uid>")
def member_statement_page(uid):
    from ..models import User
    if current_user.role not in ('admin', 'finance') and current_user.id != uid:
        return redirect(url_for('dashboard.home'))
    u = db_session.get(User, uid)
    if not u:
        return redirect(url_for('dashboard.accounting'))
    return _render("member_statement.html", target_uid=uid, target_name=u.full_name)

@bp.route("/accounting/receipt/<int:vid>")
def voucher_receipt(vid):
    from ..models import DepositVoucher
    v = db_session.get(DepositVoucher, vid)
    if not v:
        return redirect(url_for('dashboard.accounting'))
    # دسترسی: مالی/ادمین یا صاحب سند
    if current_user.role not in ('admin', 'finance') and v.user_id != current_user.id:
        return redirect(url_for('dashboard.home'))
    return _render("voucher_receipt.html", v=v.to_dict())

@bp.route("/my-payments")
def my_payments():    return _render("my_payments.html")

@bp.route("/notifications")
def notifications():  return _render("notifications.html")

@bp.route("/reports")
def reports():        return _render("reports.html")

@bp.route("/landing")
def landing():        return _render("landing_admin.html")

@bp.route("/booklet")
def booklet():        return _render("booklet.html")

@bp.route("/bale")
def bale():           return _render("bale.html")

@bp.route("/activity-log")
def activity_log():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard.home'))
    return _render("activity_log.html")

@bp.route("/tickets")
def tickets():        return _render("tickets.html")

@bp.route("/tickets/<int:tid>")
def ticket_detail(tid): return _render("ticket_detail.html", ticket_id=tid)

@bp.route("/member-profiles")
def member_profiles():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard.home'))
    return _render("member_profiles.html")


# ── بازار خرید و فروش دفترچه‌ها (Marketplace) ───────────────────────────────

@bp.route("/marketplace/my-listings")
def marketplace_my_listings():
    if current_user.role == 'admin':
        return redirect(url_for('dashboard.marketplace_admin'))
    return _render("marketplace_listings.html")

@bp.route("/marketplace/new")
def marketplace_new():
    if current_user.role == 'admin':
        return redirect(url_for('dashboard.marketplace_admin'))
    return _render("marketplace_listing_form.html", listing_id=None)

@bp.route("/marketplace/edit/<int:lid>")
def marketplace_edit(lid):
    if current_user.role == 'admin':
        return redirect(url_for('dashboard.marketplace_admin'))
    return _render("marketplace_listing_form.html", listing_id=lid)

@bp.route("/marketplace/requests")
def marketplace_requests():
    if current_user.role == 'admin':
        return redirect(url_for('dashboard.marketplace_admin'))
    return _render("marketplace_requests.html")

@bp.route("/marketplace/admin")
def marketplace_admin():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard.home'))
    return _render("marketplace_admin.html")
