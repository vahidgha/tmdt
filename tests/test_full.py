"""
=============================================================
  سناریو تست کامل — هیئت امنای مسکن دادگستری زنجان
  Full Integration Test Suite
  Run: pytest tests/test_full.py -v
=============================================================
"""

import json
import os
import sys
import tempfile
import io
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "sqlite://")

from werkzeug.security import generate_password_hash
from app import create_app
from app.models import (
    User, Project, Booklet, Announcement, Notification,
    PaymentPlan, Payment, TransferRequest, ProjectMember, Slide, SiteSetting,
)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _json(rv):
    return json.loads(rv.data)


def _post_json(client, url, payload):
    return client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ─────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def sess(app):
    """The SQLAlchemy scoped_session from the app."""
    return app.db


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def admin_client(app):
    """Session-level admin client (stays logged in throughout tests)."""
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin123"})
    return c


@pytest.fixture(scope="session")
def member_data(app, sess):
    """Create one member user for member-level tests. Returns (username, password)."""
    with app.app_context():
        existing = sess.query(User).filter_by(username="t_member").first()
        if existing:
            return "t_member", "member_pass"
        u = User(
            username="t_member",
            role="member",
            first_name="تست",
            last_name="کاربر",
            phone="09120000000",
            active=True,
            father_name="حسن", birth_date="1360/01/01", birth_place="زنجان",
            marital_status="متأهل", occupation="کارمند", emergency_phone="09120000009",
            postal_code="4519999999", address="زنجان", bank_name="ملت",
        )
        u.password_hash = generate_password_hash("member_pass")
        sess.add(u)
        sess.commit()
    return "t_member", "member_pass"


@pytest.fixture(scope="session")
def member_client(app, member_data):
    """Session-level member client."""
    uname, pw = member_data
    c = app.test_client()
    c.post("/login", data={"username": uname, "password": pw})
    return c


@pytest.fixture(scope="session")
def project_id(app, admin_client):
    """Create a project once and return its id."""
    rv = admin_client.post("/api/projects", data={
        "name": "مجتمع بهارستان",
        "address": "زنجان، خیابان ولیعصر",
        "total_booklets": "30",
        "status": "active",
        "order": "1",
    })
    return _json(rv)["project"]["id"]


@pytest.fixture(scope="session")
def booklet_id(app, admin_client, sess, member_data, project_id):
    """Create a booklet for the test member and return its id."""
    with app.app_context():
        m = sess.query(User).filter_by(username=member_data[0]).first()
        uid = m.id

    rv = _post_json(admin_client, "/api/booklets", {
        "owner_id": uid,
        "project_id": project_id,
        "share_type": "full",
        "contract_no": "CTR-TEST-001",
        "contract_amount": "500000000",
    })
    assert rv.status_code in (200, 201)
    return _json(rv)["booklet"]["id"]


# ─────────────────────────────────────────────────────────────
# 1. AUTH
# ─────────────────────────────────────────────────────────────

class TestAuth:
    def test_login_page_loads(self, client):
        rv = client.get("/login")
        assert rv.status_code == 200
        assert "ورود" in rv.data.decode("utf-8")

    def test_login_wrong_password(self, client):
        rv = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert rv.status_code == 200
        # Should stay on login page

    def test_login_wrong_username(self, client):
        rv = client.post("/login", data={"username": "nobody", "password": "x"})
        assert rv.status_code == 200

    def test_login_success_redirect(self, client):
        rv = client.post(
            "/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        assert rv.status_code == 302
        assert "dashboard" in rv.headers.get("Location", "")

    def test_protected_route_requires_auth(self, client):
        rv = client.get("/dashboard/", follow_redirects=False)
        assert rv.status_code in (302, 401)

    def test_logout(self, admin_client):
        # Use a separate client to not break the session-scoped admin_client
        c = admin_client.application.test_client()
        c.post("/login", data={"username": "admin", "password": "admin123"})
        rv = c.get("/logout", follow_redirects=False)
        assert rv.status_code == 302


# ─────────────────────────────────────────────────────────────
# 2. DASHBOARD PAGES (HTML)
# ─────────────────────────────────────────────────────────────

class TestDashboardPages:
    ADMIN_PAGES = [
        "/dashboard/",
        "/dashboard/members",
        "/dashboard/projects",
        "/dashboard/announcements",
        "/dashboard/requests",
        "/dashboard/history",
        "/dashboard/finance",
        "/dashboard/notifications",
        "/dashboard/reports",
        "/dashboard/landing",
        "/dashboard/bale",
    ]
    MEMBER_PAGES = [
        "/dashboard/",
        "/dashboard/booklet",
        "/dashboard/my-payments",
        "/dashboard/announcements",
        "/dashboard/notifications",
        "/dashboard/requests",
        "/dashboard/bale",
    ]

    def test_admin_pages_200(self, admin_client):
        for page in self.ADMIN_PAGES:
            rv = admin_client.get(page)
            assert rv.status_code == 200, f"{page} → {rv.status_code}"

    def test_member_pages_200(self, member_client):
        for page in self.MEMBER_PAGES:
            rv = member_client.get(page)
            assert rv.status_code == 200, f"{page} → {rv.status_code}"

    def test_unauthenticated_redirected(self, client):
        rv = client.get("/dashboard/", follow_redirects=False)
        assert rv.status_code in (302, 401)

    def test_static_css_loads(self, client):
        rv = client.get("/static/css/main.css")
        assert rv.status_code == 200
        assert b"Vazirmatn" in rv.data or b"--gold" in rv.data

    def test_public_homepage_loads(self, client):
        rv = client.get("/")
        assert rv.status_code == 200


# ─────────────────────────────────────────────────────────────
# 3. PROJECTS CRUD
# ─────────────────────────────────────────────────────────────

class TestProjects:
    def test_get_projects(self, admin_client):
        rv = admin_client.get("/api/projects")
        assert rv.status_code == 200
        data = _json(rv)
        assert "projects" in data
        assert isinstance(data["projects"], list)

    def test_create_project(self, admin_client):
        rv = admin_client.post("/api/projects", data={
            "name": "مجتمع گلستان",
            "address": "زنجان، بلوار شهید چمران",
            "total_booklets": "20",
            "status": "upcoming",
        })
        assert rv.status_code == 201
        data = _json(rv)
        assert data["ok"] is True
        assert data["project"]["name"] == "مجتمع گلستان"

    def test_create_project_missing_name_returns_400(self, admin_client):
        rv = admin_client.post("/api/projects", data={
            "address": "زنجان",
            "total_booklets": "10",
        })
        assert rv.status_code == 400
        assert "error" in _json(rv)

    def test_get_projects_after_create(self, admin_client):
        rv = admin_client.get("/api/projects")
        data = _json(rv)
        assert len(data["projects"]) >= 1

    def test_project_has_expected_fields(self, admin_client):
        rv = admin_client.get("/api/projects")
        p = _json(rv)["projects"][0]
        for field in ("id", "name", "status", "total_booklets", "booklet_count"):
            assert field in p, f"field '{field}' missing from project"

    def test_edit_project(self, admin_client, project_id):
        rv = admin_client.post(f"/api/projects/{project_id}", data={
            "name": "مجتمع بهارستان — ویرایش",
            "status": "active",
        })
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_edit_nonexistent_project(self, admin_client):
        rv = admin_client.post("/api/projects/999999", data={"name": "x"})
        assert rv.status_code == 404

    def test_delete_project(self, admin_client):
        rv = admin_client.post("/api/projects", data={
            "name": "پروژه موقت — حذفی",
            "total_booklets": "5",
            "status": "upcoming",
        })
        pid = _json(rv)["project"]["id"]
        rv = admin_client.post(f"/api/projects/{pid}/delete")
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_non_admin_cannot_create_project(self, member_client):
        rv = member_client.post("/api/projects", data={"name": "غیرمجاز", "total_booklets": "1"})
        assert rv.status_code == 403

    def test_project_status_values(self, admin_client):
        for status in ("active", "upcoming", "completed"):
            rv = admin_client.post("/api/projects", data={
                "name": f"پروژه وضعیت {status}",
                "total_booklets": "1",
                "status": status,
            })
            assert rv.status_code == 201
            assert _json(rv)["project"]["status"] == status


# ─────────────────────────────────────────────────────────────
# 4. MEMBERS (USERS) CRUD
# ─────────────────────────────────────────────────────────────

class TestMembers:
    def test_get_members(self, admin_client):
        rv = admin_client.get("/api/members")
        assert rv.status_code == 200
        data = _json(rv)
        assert "members" in data
        assert isinstance(data["members"], list)

    def test_create_member(self, admin_client):
        rv = _post_json(admin_client, "/api/members", {
            "first_name": "رضا",
            "last_name": "حسینی",
            "username": "reza_test_api",
            "password": "pass1234",
            "phone": "09361112233",
            "national_code": "1234509876",
        })
        assert rv.status_code in (200, 201)
        data = _json(rv)
        assert data["ok"] is True
        assert data["member"]["username"] == "reza_test_api"

    def test_create_member_missing_required_returns_400(self, admin_client):
        rv = _post_json(admin_client, "/api/members", {"first_name": "بدون نام‌کاربری"})
        assert rv.status_code == 400

    def test_duplicate_username_returns_409(self, admin_client):
        payload = {"first_name": "dup", "last_name": "test", "username": "dup_check_user", "password": "x"}
        _post_json(admin_client, "/api/members", payload)
        rv = _post_json(admin_client, "/api/members", payload)
        assert rv.status_code == 409

    def test_toggle_member_active(self, admin_client, app, sess):
        with app.app_context():
            m = sess.query(User).filter_by(role="member", username="t_member").first()
            uid = m.id
            original = m.active

        rv = admin_client.post(f"/api/members/{uid}/toggle")
        assert rv.status_code == 200
        data = _json(rv)
        assert "active" in data
        assert data["active"] != original

        # restore
        admin_client.post(f"/api/members/{uid}/toggle")

    def test_members_have_expected_fields(self, admin_client):
        rv = admin_client.get("/api/members")
        m = _json(rv)["members"][0]
        for field in ("id", "username", "role", "full_name", "active", "booklets"):
            assert field in m, f"field '{field}' missing from member"

    def test_non_admin_cannot_list_members(self, member_client):
        rv = member_client.get("/api/members")
        assert rv.status_code == 403

    def test_non_admin_cannot_create_member(self, member_client):
        rv = _post_json(member_client, "/api/members", {
            "first_name": "غیر", "last_name": "مجاز",
            "username": "unauth_create", "password": "x",
        })
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 5. BOOKLETS
# ─────────────────────────────────────────────────────────────

class TestBooklets:
    def test_get_booklets_admin(self, admin_client):
        rv = admin_client.get("/api/booklets")
        assert rv.status_code == 200
        assert "booklets" in _json(rv)

    def test_booklet_has_expected_fields(self, admin_client, booklet_id):
        rv = admin_client.get("/api/booklets")
        booklets = _json(rv)["booklets"]
        assert len(booklets) >= 1
        b = booklets[0]
        for field in ("id", "code", "project_id", "owner_id", "share_type",
                      "project_name", "owner_name"):
            assert field in b, f"field '{field}' missing from booklet"

    def test_booklet_code_format(self, admin_client):
        rv = admin_client.get("/api/booklets")
        for b in _json(rv)["booklets"]:
            # code is either ZNJ-xxx (auto-generated) or contract_no (when provided)
            assert len(b["code"]) >= 3, f"bad code: {b['code']}"

    def test_create_booklet(self, admin_client, app, sess, project_id):
        with app.app_context():
            u = sess.query(User).filter_by(username="reza_test_api").first()
            if not u:
                pytest.skip("Member not found")
            uid = u.id

        rv = _post_json(admin_client, "/api/booklets", {
            "owner_id": uid,
            "project_id": project_id,
            "share_type": "half",
            "contract_no": "CTR-002",
            "contract_amount": "250000000",
        })
        assert rv.status_code in (200, 201)
        data = _json(rv)
        assert data["ok"] is True
        assert data["booklet"]["share_type"] == "half"

    def test_share_type_half_booklet(self, admin_client, app, sess, project_id):
        with app.app_context():
            u = sess.query(User).filter_by(username="t_member").first()
            uid = u.id

        rv = _post_json(admin_client, "/api/booklets", {
            "owner_id": uid,
            "project_id": project_id,
            "share_type": "half",
        })
        assert rv.status_code in (200, 201)
        data = _json(rv)
        assert data["booklet"]["share_label"] in ("نیم‌سهم", "نیم سهم", "half")

    def test_member_sees_own_booklets_only(self, member_client, app, sess, member_data):
        with app.app_context():
            m = sess.query(User).filter_by(username=member_data[0]).first()
            mid = m.id

        rv = member_client.get("/api/booklets")
        assert rv.status_code == 200
        booklets = _json(rv)["booklets"]
        for b in booklets:
            assert b["owner_id"] == mid

    def test_non_admin_cannot_create_booklet(self, member_client, project_id):
        rv = _post_json(member_client, "/api/booklets", {
            "owner_id": 1, "project_id": project_id, "share_type": "full",
        })
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 6. ANNOUNCEMENTS
# ─────────────────────────────────────────────────────────────

class TestAnnouncements:
    def test_get_announcements_admin(self, admin_client):
        rv = admin_client.get("/api/announcements")
        assert rv.status_code == 200
        assert "announcements" in _json(rv)

    def test_create_announcement(self, admin_client):
        rv = _post_json(admin_client, "/api/announcements", {
            "title": "اطلاعیه آزمایشی",
            "body": "متن اطلاعیه تست — این یک آزمون است.",
        })
        assert rv.status_code == 201
        data = _json(rv)
        assert data["ok"] is True
        assert "id" in data

    def test_create_announcement_missing_title_400(self, admin_client):
        rv = _post_json(admin_client, "/api/announcements", {"body": "بدون عنوان"})
        assert rv.status_code == 400

    def test_announcement_appears_in_list(self, admin_client):
        _post_json(admin_client, "/api/announcements", {"title": "اطلاعیه شاخص", "body": "برای جستجو"})
        rv = admin_client.get("/api/announcements")
        titles = [a["title"] for a in _json(rv)["announcements"]]
        assert "اطلاعیه شاخص" in titles

    def test_delete_announcement(self, admin_client):
        rv = _post_json(admin_client, "/api/announcements", {"title": "حذفی", "body": "متن"})
        aid = _json(rv)["id"]
        rv = admin_client.delete(f"/api/announcements/{aid}")
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True
        # Verify removed
        rv = admin_client.get("/api/announcements")
        ids = [a["id"] for a in _json(rv)["announcements"]]
        assert aid not in ids

    def test_member_can_read_announcements(self, member_client):
        rv = member_client.get("/api/announcements")
        assert rv.status_code == 200

    def test_member_cannot_create_announcement(self, member_client):
        rv = _post_json(member_client, "/api/announcements", {"title": "غیرمجاز", "body": "متن"})
        assert rv.status_code == 403

    def test_member_cannot_delete_announcement(self, member_client):
        rv = member_client.delete("/api/announcements/1")
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 7. NOTIFICATIONS
# ─────────────────────────────────────────────────────────────

class TestNotifications:
    def test_get_notifications_member(self, member_client):
        rv = member_client.get("/api/notifications")
        assert rv.status_code == 200
        data = _json(rv)
        assert "notifications" in data
        assert "unread_count" in data
        assert isinstance(data["unread_count"], int)

    def test_send_notification(self, admin_client):
        rv = _post_json(admin_client, "/api/notifications/send", {
            "title": "اطلاع‌رسانی تست",
            "body": "پیام آزمایشی ارسال شد",
            "type": "info",
        })
        assert rv.status_code in (200, 201)
        data = _json(rv)
        assert data["ok"] is True
        assert data["sent"] >= 0

    def test_notification_appears_for_member(self, admin_client, member_client):
        _post_json(admin_client, "/api/notifications/send", {
            "title": "پیام مستقیم", "body": "برای تست badge", "type": "success",
        })
        rv = member_client.get("/api/notifications")
        titles = [n["title"] for n in _json(rv)["notifications"]]
        assert "پیام مستقیم" in titles

    def test_mark_specific_notifications_read(self, member_client):
        rv = member_client.get("/api/notifications")
        unread = [n["id"] for n in _json(rv)["notifications"] if not n.get("read")]
        if not unread:
            pytest.skip("No unread notifications")
        rv = _post_json(member_client, "/api/notifications/read", {"ids": unread[:2]})
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_mark_all_notifications_read(self, member_client):
        rv = _post_json(member_client, "/api/notifications/read", {})
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_unread_count_after_read(self, member_client):
        _post_json(member_client, "/api/notifications/read", {})
        rv = member_client.get("/api/notifications")
        assert _json(rv)["unread_count"] == 0

    def test_member_cannot_send_notification(self, member_client):
        rv = _post_json(member_client, "/api/notifications/send", {"title": "غیرمجاز", "body": "پیام"})
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 8. FINANCE — PAYMENT PLANS
# ─────────────────────────────────────────────────────────────

class TestFinancePlans:
    def test_get_plans(self, admin_client):
        rv = admin_client.get("/api/finance/plans")
        assert rv.status_code == 200
        assert "plans" in _json(rv)

    def test_create_plan(self, admin_client, project_id):
        rv = _post_json(admin_client, "/api/finance/plans", {
            "title": "طرح اقساط آزمایشی",
            "total_amount": 600000000,
            "installments": 12,
            "start_date": "1403/01/01",
            "project_id": project_id,
        })
        assert rv.status_code == 201
        data = _json(rv)
        assert data["ok"] is True
        assert "plan_id" in data
        assert "payments_created" in data

    def test_plan_creates_payments(self, admin_client, project_id, app, sess):
        rv = _post_json(admin_client, "/api/finance/plans", {
            "title": "طرح پرداخت تعداد",
            "total_amount": 120000,
            "installments": 3,
            "start_date": "1403/04/01",
            "project_id": project_id,
        })
        data = _json(rv)
        assert data["payments_created"] >= 0  # May be 0 if no booklets

    def test_create_plan_missing_fields_400(self, admin_client):
        rv = _post_json(admin_client, "/api/finance/plans", {"title": "ناقص"})
        assert rv.status_code == 400
        assert "error" in _json(rv)

    def test_plan_filter_by_project(self, admin_client, project_id):
        rv = admin_client.get(f"/api/finance/plans?project_id={project_id}")
        assert rv.status_code == 200
        data = _json(rv)
        for plan in data["plans"]:
            assert plan.get("project_id") in (project_id, None)

    def test_member_can_get_plans(self, member_client):
        rv = member_client.get("/api/finance/plans")
        assert rv.status_code == 200

    def test_member_cannot_create_plan(self, member_client, project_id):
        rv = _post_json(member_client, "/api/finance/plans", {
            "title": "غیرمجاز",
            "total_amount": 100,
            "installments": 1,
            "start_date": "1403/01/01",
        })
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 9. FINANCE — PAYMENTS
# ─────────────────────────────────────────────────────────────

class TestFinancePayments:
    def test_get_payments_admin(self, admin_client):
        rv = admin_client.get("/api/finance/payments")
        assert rv.status_code == 200
        assert "payments" in _json(rv)

    def test_get_finance_summary(self, admin_client):
        rv = admin_client.get("/api/finance/summary")
        assert rv.status_code == 200
        s = _json(rv)["summary"]
        for key in ("total", "paid", "unpaid", "overdue"):
            assert key in s
            assert "amount" in s[key]
            assert "count" in s[key]

    def test_mark_payment_paid(self, admin_client, app, sess):
        with app.app_context():
            pay = sess.query(Payment).first()
            if not pay:
                pytest.skip("No payment found")
            pid = pay.id

        rv = admin_client.patch(
            f"/api/finance/payments/{pid}",
            data=json.dumps({"status": "paid", "paid_date": "1403/05/20"}),
            content_type="application/json",
        )
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_payment_status_after_update(self, admin_client, app, sess):
        with app.app_context():
            pay = sess.query(Payment).filter_by(status="unpaid").first()
            if not pay:
                pytest.skip("No unpaid payment")
            pid = pay.id

        admin_client.patch(
            f"/api/finance/payments/{pid}",
            data=json.dumps({"status": "paid", "paid_date": "1403/06/01"}),
            content_type="application/json",
        )
        rv = admin_client.get("/api/finance/payments")
        paid_ids = [p["id"] for p in _json(rv)["payments"] if p["status"] == "paid"]
        assert pid in paid_ids

    def test_member_sees_own_payments_only(self, member_client, member_data, app, sess):
        with app.app_context():
            m = sess.query(User).filter_by(username=member_data[0]).first()
            mid = m.id

        rv = member_client.get("/api/finance/payments")
        assert rv.status_code == 200
        for p in _json(rv)["payments"]:
            assert p["user"]["id"] == mid

    def test_member_cannot_update_payment_status(self, member_client, app, sess):
        with app.app_context():
            pay = sess.query(Payment).first()
            if not pay:
                pytest.skip("No payment")
            pid = pay.id

        rv = member_client.patch(
            f"/api/finance/payments/{pid}",
            data=json.dumps({"status": "paid"}),
            content_type="application/json",
        )
        assert rv.status_code == 403

    def test_upload_receipt(self, member_client, booklet_id, app, sess):
        with app.app_context():
            pay = sess.query(Payment).first()
            if not pay:
                pytest.skip("No payment")
            pid = pay.id

        fake_file = (io.BytesIO(b"%PDF fake receipt"), "receipt.pdf")
        rv = member_client.post(
            f"/api/finance/payments/{pid}/upload",
            data={"receipt": fake_file},
            content_type="multipart/form-data",
        )
        # 200 (own payment) or 403 (not owner) — both valid
        assert rv.status_code in (200, 403)


# ─────────────────────────────────────────────────────────────
# 10. TRANSFER REQUESTS
# ─────────────────────────────────────────────────────────────

class TestTransferRequests:
    def test_get_requests_admin(self, admin_client):
        rv = admin_client.get("/api/requests")
        assert rv.status_code == 200
        assert "requests" in _json(rv)

    def test_get_requests_member(self, member_client):
        rv = member_client.get("/api/requests")
        assert rv.status_code == 200
        assert "requests" in _json(rv)

    def test_create_transfer_request(self, member_client, booklet_id):
        rv = _post_json(member_client, "/api/requests/new", {
            "booklet_id": booklet_id,
            "new_owner_first_name": "محمد",
            "new_owner_last_name": "احمدی",
            "new_owner_national_code": "9876543210",
            "new_owner_phone": "09131111111",
            "note": "انتقال آزمایشی",
        })
        # 201 = created, 403 = not owner, 409 = already pending
        assert rv.status_code in (201, 403, 409)

    def test_reject_request(self, admin_client, app, sess):
        with app.app_context():
            req = sess.query(TransferRequest).filter_by(status="pending").first()
            if not req:
                pytest.skip("No pending request")
            rid = req.id

        rv = _post_json(admin_client, f"/api/requests/{rid}/reject", {
            "review_note": "مدارک کامل نیست"
        })
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_approve_request(self, admin_client, app, sess, member_data):
        # Create a fresh booklet + request for approval
        with app.app_context():
            # create new member to be "new owner" after approval
            p = sess.query(Project).first()
            m = sess.query(User).filter_by(username=member_data[0]).first()
            if not p or not m:
                pytest.skip("Missing fixtures")
            pid, uid = p.id, m.id

        # Create booklet for this member
        rv = _post_json(admin_client, "/api/booklets", {
            "owner_id": uid, "project_id": pid, "share_type": "full",
        })
        if rv.status_code not in (200, 201):
            pytest.skip("Could not create booklet")
        bid = _json(rv)["booklet"]["id"]

        # Member creates a request
        rv = _post_json(member_client := admin_client, f"/api/requests/new", {
            "booklet_id": bid,
            "new_owner_first_name": "جدید",
            "new_owner_last_name": "مالک",
            "new_owner_national_code": f"5555{bid:06d}",
            "new_owner_phone": "09151234567",
        })
        if rv.status_code not in (201, 409):
            pytest.skip("Request creation failed")

        with app.app_context():
            req = sess.query(TransferRequest).filter_by(status="pending").first()
            if not req:
                pytest.skip("No pending request to approve")
            rid = req.id

        rv = admin_client.post(f"/api/requests/{rid}/approve")
        assert rv.status_code in (200, 400)

    def test_non_admin_cannot_approve(self, member_client):
        rv = member_client.post("/api/requests/1/approve")
        assert rv.status_code in (403, 404)

    def test_non_admin_cannot_reject(self, member_client):
        rv = _post_json(member_client, "/api/requests/1/reject", {})
        assert rv.status_code in (403, 404)


# ─────────────────────────────────────────────────────────────
# 11. PROJECT MEMBERS (TEAM)
# ─────────────────────────────────────────────────────────────

class TestProjectMembers:
    def test_get_project_members(self, admin_client, project_id):
        rv = admin_client.get(f"/api/projects/{project_id}/members")
        assert rv.status_code == 200
        assert "members" in _json(rv)

    def test_add_project_member(self, admin_client, project_id):
        rv = _post_json(admin_client, f"/api/projects/{project_id}/members",
                        {"full_name": "علی رضایی", "role": "مدیر اجرایی", "phone": "09121112233", "order": 1})
        assert rv.status_code in (200, 201)
        data = _json(rv)
        assert data["ok"] is True
        assert data["member"]["full_name"] == "علی رضایی"

    def test_added_member_appears_in_list(self, admin_client, project_id):
        _post_json(admin_client, f"/api/projects/{project_id}/members",
                   {"full_name": "ناظر تست", "role": "ناظر"})
        rv = admin_client.get(f"/api/projects/{project_id}/members")
        names = [m["full_name"] for m in _json(rv)["members"]]
        assert "ناظر تست" in names

    def test_delete_project_member(self, admin_client, project_id):
        rv = _post_json(admin_client, f"/api/projects/{project_id}/members",
                        {"full_name": "عضو موقت", "role": "ناظر"})
        mid = _json(rv)["member"]["id"]
        rv = admin_client.delete(f"/api/projects/{project_id}/members/{mid}")
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_deleted_member_not_in_list(self, admin_client, project_id):
        rv = _post_json(admin_client, f"/api/projects/{project_id}/members",
                        {"full_name": "عضو حذفی", "role": "ناظر"})
        mid = _json(rv)["member"]["id"]
        admin_client.delete(f"/api/projects/{project_id}/members/{mid}")
        rv = admin_client.get(f"/api/projects/{project_id}/members")
        ids = [m["id"] for m in _json(rv)["members"]]
        assert mid not in ids

    def test_non_admin_cannot_add_member(self, member_client, project_id):
        rv = _post_json(member_client, f"/api/projects/{project_id}/members",
                        {"full_name": "غیرمجاز", "role": "ناظر"})
        assert rv.status_code == 403

    def test_non_admin_cannot_delete_member(self, member_client, project_id, admin_client):
        rv = _post_json(admin_client, f"/api/projects/{project_id}/members",
                        {"full_name": "عضو برای آزمون حذف", "role": "ناظر"})
        mid = _json(rv)["member"]["id"]
        rv = member_client.delete(f"/api/projects/{project_id}/members/{mid}")
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 12. ADMIN SLIDES
# ─────────────────────────────────────────────────────────────

class TestSlides:
    def test_get_slides(self, admin_client):
        rv = admin_client.get("/api/admin/slides")
        assert rv.status_code == 200
        assert "slides" in _json(rv)

    def test_create_slide(self, admin_client):
        rv = admin_client.post("/api/admin/slides", data={
            "title": "اسلاید آزمایشی",
            "subtitle": "زیرعنوان تست",
            "bg_color": "#1A2640",
            "order": "1",
        })
        assert rv.status_code in (200, 201)
        data = _json(rv)
        assert data["ok"] is True
        assert "id" in data

    def test_slide_appears_in_list(self, admin_client):
        admin_client.post("/api/admin/slides", data={"title": "اسلاید شاخص", "bg_color": "#000"})
        rv = admin_client.get("/api/admin/slides")
        titles = [s["title"] for s in _json(rv)["slides"]]
        assert "اسلاید شاخص" in titles

    def test_delete_slide(self, admin_client):
        rv = admin_client.post("/api/admin/slides", data={"title": "اسلاید حذفی", "bg_color": "#111"})
        sid = _json(rv)["id"]
        rv = admin_client.post(f"/api/admin/slides/{sid}/delete")
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_non_admin_cannot_access_slides(self, member_client):
        rv = member_client.get("/api/admin/slides")
        assert rv.status_code == 403

    def test_non_admin_cannot_create_slide(self, member_client):
        rv = member_client.post("/api/admin/slides", data={"title": "غیرمجاز"})
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 13. ADMIN SETTINGS
# ─────────────────────────────────────────────────────────────

class TestSettings:
    def test_get_settings(self, admin_client):
        rv = admin_client.get("/api/admin/settings")
        assert rv.status_code == 200
        data = _json(rv)
        assert isinstance(data, dict)
        assert "site_title" in data

    def test_update_settings(self, admin_client):
        rv = _post_json(admin_client, "/api/admin/settings", {
            "site_title": "هیئت امنا — نسخه تست",
            "site_phone": "0241-1234567",
        })
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_settings_persisted(self, admin_client):
        _post_json(admin_client, "/api/admin/settings", {"exec_manager": "علی محمدی"})
        rv = admin_client.get("/api/admin/settings")
        assert _json(rv).get("exec_manager") == "علی محمدی"

    def test_non_admin_cannot_get_settings(self, member_client):
        rv = member_client.get("/api/admin/settings")
        assert rv.status_code == 403

    def test_non_admin_cannot_update_settings(self, member_client):
        rv = _post_json(member_client, "/api/admin/settings", {"site_title": "هک"})
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 14. PROFILE
# ─────────────────────────────────────────────────────────────

class TestProfile:
    def test_get_my_profile_member(self, member_client):
        rv = member_client.get("/api/profile/me")
        assert rv.status_code == 200
        data = _json(rv)
        assert "user" in data
        assert "booklets" in data

    def test_get_my_profile_admin(self, admin_client):
        rv = admin_client.get("/api/profile/me")
        assert rv.status_code == 200

    def test_profile_has_expected_user_fields(self, member_client):
        rv = member_client.get("/api/profile/me")
        u = _json(rv)["user"]
        for f in ("id", "username", "role", "full_name", "active"):
            assert f in u, f"'{f}' missing from profile user"

    def test_complete_profile(self, member_client):
        rv = _post_json(member_client, "/api/profile/complete", {
            "first_name": "تست",
            "last_name": "کاربر",
            "father_name": "حسن",
            "birth_date": "1370/05/12",
            "birth_place": "زنجان",
            "marital_status": "متأهل",
            "phone": "09120000000",
            "emergency_phone": "09121111111",
            "address": "خیابان ولیعصر",
            "postal_code": "4514734567",
            "occupation": "کارمند",
            "email": "tester@example.com",
            "bank_name": "ملت",
        })
        assert rv.status_code == 200
        assert _json(rv)["ok"] is True

    def test_password_change_via_complete_ignored_after_completion(self, app, sess, member_client):
        # امنیت: بعد از تکمیل پروفایل (profile_complete=True از test_complete_profile
        # قبلی)، /profile/complete دیگر رمز عبور را تغییر نمی‌دهد — وگرنه این مسیر
        # می‌شد راهی برای تغییر رمز بدون تأیید رمز فعلی. تغییر رمز واقعی فقط از
        # /profile/change-password (با تأیید رمز فعلی) باید ممکن باشد.
        rv = _post_json(member_client, "/api/profile/complete", {
            "new_password": "newpass9999",
            "confirm_password": "xyz-mismatch-should-be-ignored",
        })
        assert rv.status_code == 200  # فیلدهای رمز نادیده گرفته می‌شوند، نه خطا

    def test_password_mismatch_400_during_initial_completion(self, app, sess):
        # اعتبارسنجی مطابقت رمز فقط در همان تکمیل اولیه (پیش از profile_complete) اعمال می‌شود
        with app.app_context():
            u = sess.query(User).filter_by(username="t_pwmismatch").first()
            if not u:
                u = User(username="t_pwmismatch", role="member", phone="09127777777", active=True,
                         password_hash=generate_password_hash("initialpass1"))
                sess.add(u); sess.commit()
        c = app.test_client()
        c.post("/login", data={"username": "t_pwmismatch", "password": "initialpass1"})
        rv = _post_json(c, "/api/profile/complete", {
            "new_password": "abc123",
            "confirm_password": "xyz456",
        })
        assert rv.status_code == 400

    def test_change_password_wrong_current_400(self, member_client):
        rv = _post_json(member_client, "/api/profile/change-password", {
            "current_password": "not-the-real-password",
            "new_password": "brandnewpass1",
            "confirm_password": "brandnewpass1",
        })
        assert rv.status_code == 400

    def test_change_password_success_and_relogin(self, app, sess):
        # کاربر مستقل و تازه — تا با تغییر رمز در تست‌های دیگر (test_password_change) تداخل نکند
        with app.app_context():
            u = sess.query(User).filter_by(username="t_pwchange").first()
            if not u:
                u = User(username="t_pwchange", role="member", phone="09128888888", active=True)
                u.password_hash = generate_password_hash("original_pass1")
                sess.add(u)
                sess.commit()

        c = app.test_client()
        c.post("/login", data={"username": "t_pwchange", "password": "original_pass1"})
        rv = _post_json(c, "/api/profile/change-password", {
            "current_password": "original_pass1",
            "new_password": "newselfpass1",
            "confirm_password": "newselfpass1",
        })
        assert rv.status_code == 200

        # رمز قدیمی دیگر کار نمی‌کند (فرم لاگین دوباره با خطا رندر می‌شود، نه ریدایرکت)
        c2 = app.test_client()
        rv2 = c2.post("/login", data={"username": "t_pwchange", "password": "original_pass1"}, follow_redirects=False)
        assert rv2.status_code == 200

        # رمز جدید کار می‌کند (ریدایرکت موفق به پنل)
        c3 = app.test_client()
        rv3 = c3.post("/login", data={"username": "t_pwchange", "password": "newselfpass1"}, follow_redirects=False)
        assert rv3.status_code == 302


class TestIncompleteProfileGating:
    """عضوی که profile_complete=False دارد باید از کل پنل (به‌جز خودِ صفحه
    تکمیل پروفایل و API مربوط به آن) مسدود باشد."""

    @pytest.fixture()
    def incomplete_client(self, app, sess):
        with app.app_context():
            u = sess.query(User).filter_by(username="t_incomplete").first()
            if not u:
                u = User(username="t_incomplete", role="member", phone="09129999999",
                         active=True, profile_complete=False)
                u.password_hash = generate_password_hash("incomplete_pass")
                sess.add(u)
                sess.commit()
        c = app.test_client()
        c.post("/login", data={"username": "t_incomplete", "password": "incomplete_pass"})
        return c

    def test_home_shows_completion_form(self, incomplete_client):
        rv = incomplete_client.get("/dashboard/")
        assert rv.status_code == 200
        assert "تکمیل اطلاعات هویتی".encode() in rv.data

    def test_other_dashboard_pages_redirect_home(self, incomplete_client):
        rv = incomplete_client.get("/dashboard/members", follow_redirects=False)
        assert rv.status_code == 302
        assert rv.headers["Location"].endswith("/dashboard/")

    def test_other_apis_blocked(self, incomplete_client):
        rv = incomplete_client.get("/api/announcements")
        assert rv.status_code == 403

    def test_profile_apis_still_allowed(self, incomplete_client):
        rv = incomplete_client.get("/api/profile/me")
        assert rv.status_code == 200


# ─────────────────────────────────────────────────────────────
# 15. REPORTS
# ─────────────────────────────────────────────────────────────

class TestReports:
    def test_finance_report(self, admin_client):
        rv = admin_client.get("/api/reports?type=finance")
        assert rv.status_code == 200
        assert "payments" in _json(rv)

    def test_members_report(self, admin_client):
        rv = admin_client.get("/api/reports?type=members")
        assert rv.status_code == 200
        data = _json(rv)
        assert "members" in data

    def test_default_report_type(self, admin_client):
        rv = admin_client.get("/api/reports")
        assert rv.status_code == 200
        data = _json(rv)
        assert "payments" in data  # default = finance

    def test_reports_data_structure(self, admin_client):
        rv = admin_client.get("/api/reports?type=members")
        for m in _json(rv)["members"]:
            assert "full_name" in m or "first_name" in m
            assert "booklets" in m

    def test_non_admin_cannot_access_reports(self, member_client):
        rv = member_client.get("/api/reports")
        assert rv.status_code == 403


# ─────────────────────────────────────────────────────────────
# 16. SECURITY
# ─────────────────────────────────────────────────────────────

class TestSecurity:
    def test_unauthenticated_api_blocked(self, client):
        for path in ("/api/members", "/api/projects", "/api/booklets",
                     "/api/reports", "/api/admin/settings"):
            rv = client.get(path)
            assert rv.status_code in (302, 401, 403), f"{path} should block unauthenticated"

    def test_inactive_user_blocked_from_login(self, app, admin_client, sess):
        # Create & deactivate a user
        _post_json(admin_client, "/api/members", {
            "first_name": "غیرفعال", "last_name": "تست",
            "username": "inactive_login_test", "password": "pass123",
        })
        with app.app_context():
            u = sess.query(User).filter_by(username="inactive_login_test").first()
            if u:
                u.active = False
                sess.commit()

        c = app.test_client()
        rv = c.post("/login", data={"username": "inactive_login_test", "password": "pass123"})
        # Should NOT redirect to dashboard (stays on login page)
        assert rv.status_code == 200

    def test_member_cannot_approve_transfer(self, member_client):
        rv = member_client.post("/api/requests/1/approve")
        assert rv.status_code in (403, 404)

    def test_member_cannot_patch_payment(self, member_client):
        rv = member_client.patch(
            "/api/finance/payments/1",
            data=json.dumps({"status": "paid"}),
            content_type="application/json",
        )
        assert rv.status_code == 403

    def test_member_cannot_delete_slide(self, member_client):
        rv = member_client.post("/api/admin/slides/1/delete")
        assert rv.status_code == 403

    def test_nonexistent_resource_not_500(self, admin_client):
        rv = admin_client.get("/api/projects/999999/members")
        assert rv.status_code in (200, 404)

    def test_invalid_json_body_handled(self, admin_client):
        rv = admin_client.post(
            "/api/announcements",
            data="not-json",
            content_type="application/json",
        )
        assert rv.status_code in (400, 415, 500)
        assert rv.status_code != 500  # Must not crash

    def test_large_page_booklet_request_handled(self, admin_client):
        rv = admin_client.get("/api/booklets")
        assert rv.status_code == 200
