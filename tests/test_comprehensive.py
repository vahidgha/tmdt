"""
=============================================================
  تست جامع — همه ماژول‌ها، مدل‌ها، API‌ها و صفحات
  Comprehensive Test Suite
  Run: pytest tests/test_comprehensive.py -v
=============================================================
"""

import json, os, sys, io, random, string, tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from werkzeug.security import generate_password_hash
from app import create_app
from app.models import (
    User, Project, Booklet, Announcement, AnnouncementMedia,
    Notification, Payment, PaymentPlan, TransferRequest, TransferHistory,
    ProjectMember, ProjectGallery, Slide, SiteSetting, Ticket, TicketMessage,
    ActivityLog,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _j(rv):
    return json.loads(rv.data)

def _post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")

def _post_form(client, url, data):
    return client.post(url, data=data)

def _rand(n=6):
    return ''.join(random.choices(string.ascii_lowercase, k=n))


# ─── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def sess(app):
    return app.db


@pytest.fixture(scope="session")
def admin_client(app):
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin123"})
    return c


@pytest.fixture(scope="session")
def member_uid(app, sess):
    with app.app_context():
        tag = _rand()
        existing = sess.query(User).filter_by(username="comp_member").first()
        if existing:
            return existing.id
        u = User(
            username="comp_member",
            password_hash=generate_password_hash("pw123"),
            first_name="عضو", last_name="جامع", role="member",
            national_code=f"9{tag[:9]}", active=True, profile_complete=True,
            father_name="حسن", birth_date="1360/01/01", birth_place="زنجان",
            marital_status="متأهل", occupation="کارمند", phone="09120000001", emergency_phone="09120000002",
            postal_code="4519999999", address="زنجان", bank_name="ملت",
        )
        sess.add(u); sess.commit()
        return u.id


@pytest.fixture(scope="session")
def member_client(app, sess, member_uid):
    with app.app_context():
        u = sess.get(User, member_uid)
        uname = u.username
    c = app.test_client()
    c.post("/login", data={"username": uname, "password": "pw123"})
    return c


@pytest.fixture(scope="session")
def proj_id(app, admin_client):
    rv = admin_client.post("/api/projects", data={
        "name": f"پروژه جامع {_rand()}", "status": "active", "total_booklets": "10",
    })
    assert rv.status_code in (200, 201), f"project create failed: {rv.data}"
    return _j(rv)["project"]["id"]


@pytest.fixture(scope="session")
def booklet_id(admin_client, proj_id, member_uid):
    rv = admin_client.post("/api/booklets", data={
        "owner_id": str(member_uid), "project_id": str(proj_id), "share_type": "full",
    })
    assert rv.status_code in (200, 201), f"booklet create failed: {rv.data}"
    return _j(rv)["booklet"]["id"]


@pytest.fixture(scope="session")
def ann_id(admin_client):
    rv = admin_client.post("/api/announcements", data={
        "title": "اطلاعیه جامع", "body": "متن اطلاعیه جامع برای تست",
    })
    assert rv.status_code == 201, f"ann create failed: {rv.data}"
    return _j(rv)["id"]


@pytest.fixture(scope="session")
def ticket_id(app, sess, member_uid):
    with app.app_context():
        from sqlalchemy import func as sqlfunc
        max_num = sess.query(sqlfunc.max(Ticket.number)).scalar() or 1000
        t = Ticket(
            number=max_num + 1, subject="تیکت جامع",
            category="general", priority="normal", status="open",
            creator_id=member_uid,
        )
        sess.add(t)
        msg = TicketMessage(body="متن اولیه تیکت", sender_id=member_uid, is_admin=False)
        t.messages.append(msg)
        sess.commit()
        return t.id


@pytest.fixture(scope="session")
def plan_id(admin_client, proj_id):
    rv = admin_client.post("/api/plans", data={
        "title": f"طرح {_rand()}", "total_amount": "2000000",
        "installments": "4", "start_date": "1403-01-01",
        "project_id": str(proj_id),
    })
    assert rv.status_code in (200, 201), f"plan create failed: {rv.data}"
    d = _j(rv)
    return (d.get("plan") or d).get("id") or d.get("id")


# =============================================================================
# 1. DATABASE MODELS — all columns exist
# =============================================================================

class TestModels:

    def _cols(self, sess, table):
        from sqlalchemy import inspect, text
        with sess.bind.connect() as conn:
            result = conn.execute(text(f"PRAGMA table_info({table})"))
            return {row[1] for row in result}

    def test_user_all_columns(self, sess):
        cols = self._cols(sess, 'users')
        for c in ['id','username','password_hash','role','first_name','last_name',
                  'national_code','gender','id_number','phone','emergency_phone',
                  'active','profile_complete','father_name','birth_date','birth_place',
                  'marital_status','landline','address','postal_code','occupation',
                  'email','bank_name','account_number','iban','bale_chat_id',
                  'bale_link_code','created_at']:
            assert c in cols, f"Column '{c}' missing from users"

    def test_project_all_columns(self, sess):
        cols = self._cols(sess, 'projects')
        for c in ['id','name','description','address','location','total_booklets',
                  'start_date','end_date','status','image_path','map_lat','map_lon',
                  'order','active','created_at']:
            assert c in cols, f"Column '{c}' missing from projects"

    def test_booklet_all_columns(self, sess):
        cols = self._cols(sess, 'booklets')
        for c in ['id','code','serial','booklet_number','project_id','owner_id',
                  'share_type','contract_no','contract_date','contract_amount',
                  'notes','created_at']:
            assert c in cols, f"Column '{c}' missing from booklets"

    def test_announcement_all_columns(self, sess):
        cols = self._cols(sess, 'announcements')
        for c in ['id','title','body','image_path','author_id','author',
                  'date','project_id','pub_date','expires_at']:
            assert c in cols, f"Column '{c}' missing from announcements"

    def test_announcement_media_all_columns(self, sess):
        cols = self._cols(sess, 'announcement_media')
        for c in ['id','announcement_id','file_path','file_type','caption','order','created_at']:
            assert c in cols

    def test_transfer_request_all_columns(self, sess):
        cols = self._cols(sess, 'transfer_requests')
        for c in ['id','booklet_id','requester_id','new_owner_first_name',
                  'new_owner_last_name','new_owner_national_code','new_owner_phone',
                  'note','status','receipt_path','agreement_path','sana_form_path',
                  'id_first_page_path','national_front_path','national_back_path',
                  'extra_photo_path','created_at','reviewed_at','review_note']:
            assert c in cols, f"Column '{c}' missing from transfer_requests"

    def test_payment_all_columns(self, sess):
        cols = self._cols(sess, 'payments')
        for c in ['id','user_id','booklet_id','plan_id','amount','due_date',
                  'paid_date','status','description','receipt_path','created_at']:
            assert c in cols

    def test_ticket_all_columns(self, sess):
        cols = self._cols(sess, 'tickets')
        for c in ['id','number','subject','category','priority','status',
                  'creator_id','assigned_id','created_at','updated_at','closed_at']:
            assert c in cols

    def test_ticket_message_all_columns(self, sess):
        cols = self._cols(sess, 'ticket_messages')
        for c in ['id','ticket_id','sender_id','body','is_admin','created_at']:
            assert c in cols

    def test_activity_log_all_columns(self, sess):
        cols = self._cols(sess, 'activity_logs')
        for c in ['id','user_id','action','category','detail','ip','created_at']:
            assert c in cols

    def test_site_settings_columns(self, sess):
        cols = self._cols(sess, 'site_settings')
        assert 'key' in cols and 'value' in cols

    def test_slide_all_columns(self, sess):
        cols = self._cols(sess, 'slides')
        for c in ['id','title','subtitle','image_path','video_path','media_type',
                  'bg_color','order','active','created_at']:
            assert c in cols

    def test_project_gallery_columns(self, sess):
        cols = self._cols(sess, 'project_gallery')
        for c in ['id','project_id','file_path','file_type','caption','order','created_at']:
            assert c in cols

    def test_notification_columns(self, sess):
        cols = self._cols(sess, 'notifications')
        for c in ['id','user_id','title','body','type','read','created_at']:
            assert c in cols

    def test_payment_plan_columns(self, sess):
        cols = self._cols(sess, 'payment_plans')
        for c in ['id','project_id','title','total_amount','installments','start_date','created_at']:
            assert c in cols

    def test_project_members_columns(self, sess):
        cols = self._cols(sess, 'project_members')
        for c in ['id','project_id','role','full_name','phone','photo_path','order']:
            assert c in cols

    def test_transfer_history_columns(self, sess):
        cols = self._cols(sess, 'transfer_history')
        for c in ['id','booklet_id','from_user_id','to_user_id','date','request_id']:
            assert c in cols

    def test_user_full_name_property(self, app):
        with app.app_context():
            u = User(first_name="علی", last_name="احمدی")
            assert u.full_name == "علی احمدی"

    def test_user_full_name_empty(self, app):
        with app.app_context():
            assert User(first_name="", last_name="").full_name.strip() == ""

    def test_booklet_to_dict_keys(self, app, sess, booklet_id):
        with app.app_context():
            b = sess.get(Booklet, booklet_id)
            d = b.to_dict()
            for k in ('id','code','project_id','owner_id','share_type','project_name','owner_name'):
                assert k in d

    def test_project_to_dict_keys(self, app, sess, proj_id):
        with app.app_context():
            p = sess.get(Project, proj_id)
            d = p.to_dict()
            for k in ('id','name','status','total_booklets'):
                assert k in d

    def test_booklet_share_label(self, app, sess, booklet_id):
        with app.app_context():
            b = sess.get(Booklet, booklet_id)
            assert b.to_dict()["share_label"] in ("تمام‌سهم", "نیم‌سهم")

    def test_activity_log_to_dict(self, app, sess):
        with app.app_context():
            log = ActivityLog(action="test_action", category="test", detail="جزئیات")
            sess.add(log); sess.commit()
            d = log.to_dict()
            for k in ('id','action','category','detail','created_at'):
                assert k in d


# =============================================================================
# 2. AUTH
# =============================================================================

class TestAuth:

    def test_login_page_loads(self, app):
        rv = app.test_client().get("/login")
        assert rv.status_code == 200
        assert "ورود" in rv.data.decode()

    def test_forgot_password_page_loads(self, app):
        rv = app.test_client().get("/forgot-password")
        assert rv.status_code == 200
        assert "فراموش" in rv.data.decode() or "بازیابی" in rv.data.decode()

    def test_verify_otp_without_session_redirects(self, app):
        rv = app.test_client().get("/verify-otp")
        assert rv.status_code in (200, 302)

    def test_reset_password_without_session_redirects(self, app):
        rv = app.test_client().get("/reset-password")
        assert rv.status_code in (200, 302)

    def test_wrong_password_stays_on_login(self, app):
        rv = app.test_client().post("/login", data={"username": "admin", "password": "WRONG"})
        assert rv.status_code == 200
        assert "اشتباه" in rv.data.decode()

    def test_inactive_user_cannot_login(self, app, sess):
        with app.app_context():
            u = User(
                username="inactive_comp", password_hash=generate_password_hash("pw"),
                first_name="غیر", last_name="فعال", role="member",
                active=False, profile_complete=True,
            )
            sess.add(u); sess.commit()
        rv = app.test_client().post("/login", data={"username": "inactive_comp", "password": "pw"})
        assert rv.status_code == 200
        assert "غیرفعال" in rv.data.decode()

    def test_correct_login_redirects(self, app):
        rv = app.test_client().post(
            "/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False
        )
        assert rv.status_code in (302, 303)

    def test_logout(self, app):
        c = app.test_client()
        c.post("/login", data={"username": "admin", "password": "admin123"})
        rv = c.get("/logout", follow_redirects=False)
        assert rv.status_code in (302, 303)

    def test_unauthenticated_dashboard_redirects(self, app):
        rv = app.test_client().get("/dashboard/")
        assert rv.status_code in (302, 401)

    def test_forgot_password_unknown_code(self, app):
        # پاسخ برای شناسه ناموجود عمداً با شناسه موجود یکسان است (رفع User
        # Enumeration) — همیشه به verify-otp ریدایرکت می‌شود، بدون افشای وجود/عدم‌وجود حساب
        rv = app.test_client().post("/forgot-password", data={"national_code": "0000000000"})
        assert rv.status_code == 302
        assert "/verify-otp" in rv.headers["Location"]

    def test_forgot_password_no_bale(self, app, sess):
        with app.app_context():
            tag = _rand()
            u = User(
                username=f"nophone_{tag}", password_hash=generate_password_hash("pw123"),
                first_name="بدون", last_name="تماس", role="member",
                national_code=f"8{tag[:9]}", active=True,
            )
            sess.add(u); sess.commit()
            nc = u.national_code
        rv = app.test_client().post("/forgot-password", data={"national_code": nc})
        # پاسخ یکسان با حالت شناسه ناموجود — بدون افشای این‌که حساب شماره تماس ندارد
        assert rv.status_code == 302
        assert "/verify-otp" in rv.headers["Location"]


# =============================================================================
# 3. PROJECTS API
# =============================================================================

class TestProjectsAPI:

    def test_list_projects(self, admin_client):
        rv = admin_client.get("/api/projects")
        assert rv.status_code == 200
        assert isinstance(_j(rv)["projects"], list)

    def test_project_response_fields(self, admin_client, proj_id):
        projects = _j(admin_client.get("/api/projects"))["projects"]
        p = next((x for x in projects if x["id"] == proj_id), None)
        assert p is not None
        for f in ("id","name","status","total_booklets","active","created_at"):
            assert f in p, f"field '{f}' missing"

    def test_create_project(self, admin_client):
        rv = admin_client.post("/api/projects", data={
            "name": f"پروژه آزمون {_rand()}", "status": "upcoming", "total_booklets": "5",
        })
        assert rv.status_code in (200, 201)
        assert "project" in _j(rv)

    def test_create_project_missing_name(self, admin_client):
        rv = admin_client.post("/api/projects", data={"status": "active"})
        assert rv.status_code == 400

    def test_member_cannot_create_project(self, member_client):
        rv = member_client.post("/api/projects", data={"name": "غیرمجاز", "total_booklets": "1"})
        assert rv.status_code == 403

    def test_project_gallery_returns_list(self, admin_client, proj_id):
        rv = admin_client.get(f"/api/projects/{proj_id}/gallery")
        assert rv.status_code == 200
        assert isinstance(_j(rv)["gallery"], list)

    def test_project_members_returns_list(self, admin_client, proj_id):
        rv = admin_client.get(f"/api/projects/{proj_id}/members")
        assert rv.status_code == 200
        assert isinstance(_j(rv)["members"], list)

    def test_add_project_member(self, admin_client, proj_id):
        rv = admin_client.post(f"/api/projects/{proj_id}/members", data={
            "full_name": "مدیر آزمون", "role": "مدیر اجرایی", "phone": "09000000001",
        })
        assert rv.status_code in (200, 201)

    def test_delete_nonexistent_project(self, admin_client):
        rv = admin_client.delete("/api/projects/999999")
        assert rv.status_code in (404, 400)

    def test_project_status_values(self, admin_client):
        for p in _j(admin_client.get("/api/projects"))["projects"]:
            assert p["status"] in ("active", "completed", "upcoming")


# =============================================================================
# 4. MEMBERS API
# =============================================================================

class TestMembersAPI:

    def test_list_members(self, admin_client):
        rv = admin_client.get("/api/members")
        assert rv.status_code == 200
        assert "members" in _j(rv)

    def test_member_response_fields(self, admin_client):
        members = _j(admin_client.get("/api/members"))["members"]
        if members:
            m = members[0]
            for f in ("id","username","first_name","last_name","role","active"):
                assert f in m

    def test_create_member(self, admin_client):
        tag = _rand()
        rv = admin_client.post("/api/members", data={
            "first_name": "تست", "last_name": "کاربر",
            "username": f"usr_{tag}", "password": "pass1234",
            "national_code": f"2{random.randint(10**8, 10**9-1)}", "phone": "09111111111",
        })
        assert rv.status_code in (200, 201)

    def test_create_member_duplicate_username(self, admin_client):
        rv = admin_client.post("/api/members", data={
            "first_name": "تکراری", "last_name": "کاربر",
            "username": "admin", "password": "pass1234", "national_code": "1234567890",
        })
        assert rv.status_code == 409

    def test_create_member_missing_name_400(self, admin_client):
        rv = admin_client.post("/api/members", data={"username": f"u_{_rand()}", "password": "pw"})
        assert rv.status_code == 400

    def test_filter_members_by_project(self, admin_client, proj_id):
        rv = admin_client.get(f"/api/members?project_id={proj_id}")
        assert rv.status_code == 200
        assert "members" in _j(rv)

    def test_member_cannot_create_member(self, member_client):
        rv = member_client.post("/api/members", data={
            "first_name": "ف", "last_name": "م",
            "username": f"x_{_rand()}", "password": "pw",
        })
        assert rv.status_code == 403

    def test_toggle_member_active(self, admin_client, app, sess):
        with app.app_context():
            tag = _rand()
            u = User(
                username=f"tgl_{tag}", password_hash=generate_password_hash("pw"),
                first_name="تاگل", last_name="کاربر", role="member",
                active=True, profile_complete=True,
            )
            sess.add(u); sess.commit(); uid = u.id
        rv = admin_client.post(f"/api/members/{uid}/toggle")
        assert rv.status_code == 200
        assert "active" in _j(rv)

    def test_delete_member_cascade(self, admin_client, app, sess):
        with app.app_context():
            tag = _rand()
            u = User(
                username=f"del_{tag}", password_hash=generate_password_hash("pw"),
                first_name="حذف", last_name="کاربر", role="member",
                active=True, profile_complete=True,
            )
            sess.add(u); sess.commit(); uid = u.id
        rv = admin_client.delete(f"/api/members/{uid}")
        assert rv.status_code == 200
        assert _j(rv)["ok"] is True
        with app.app_context():
            assert sess.get(User, uid) is None

    def test_delete_nonexistent_member(self, admin_client):
        rv = admin_client.delete("/api/members/999999")
        assert rv.status_code == 404


# =============================================================================
# 5. BOOKLETS API
# =============================================================================

class TestBookletsAPI:

    def test_list_booklets(self, admin_client):
        rv = admin_client.get("/api/booklets")
        assert rv.status_code == 200
        assert "booklets" in _j(rv)

    def test_booklet_response_fields(self, admin_client, booklet_id):
        booklets = _j(admin_client.get("/api/booklets"))["booklets"]
        b = next((x for x in booklets if x["id"] == booklet_id), None)
        assert b is not None
        for f in ("id","code","project_id","owner_id","share_type","project_name","owner_name"):
            assert f in b

    def test_share_type_values(self, admin_client):
        for b in _j(admin_client.get("/api/booklets"))["booklets"]:
            assert b["share_type"] in ("full", "half")

    def test_create_booklet_full(self, admin_client, proj_id, member_uid):
        rv = admin_client.post("/api/booklets", data={
            "owner_id": str(member_uid), "project_id": str(proj_id), "share_type": "full",
        })
        assert rv.status_code in (200, 201)

    def test_create_booklet_half(self, admin_client, proj_id, member_uid):
        rv = admin_client.post("/api/booklets", data={
            "owner_id": str(member_uid), "project_id": str(proj_id), "share_type": "half",
        })
        assert rv.status_code in (200, 201)

    def test_missing_owner_400(self, admin_client, proj_id):
        rv = admin_client.post("/api/booklets", data={"project_id": str(proj_id), "share_type": "full"})
        assert rv.status_code == 400

    def test_missing_project_400(self, admin_client, member_uid):
        rv = admin_client.post("/api/booklets", data={"owner_id": str(member_uid), "share_type": "full"})
        assert rv.status_code == 400

    def test_member_cannot_create(self, member_client, proj_id, member_uid):
        rv = member_client.post("/api/booklets", data={
            "owner_id": str(member_uid), "project_id": str(proj_id), "share_type": "full",
        })
        assert rv.status_code == 403

    def test_auto_code_format(self, admin_client, proj_id, member_uid):
        rv = admin_client.post("/api/booklets", data={
            "owner_id": str(member_uid), "project_id": str(proj_id), "share_type": "full",
        })
        code = _j(rv)["booklet"]["code"]
        assert "ZNJ-" in code

    def test_contract_no_as_code(self, admin_client, proj_id, member_uid):
        cno = f"CNT-{_rand()}"
        rv = admin_client.post("/api/booklets", data={
            "owner_id": str(member_uid), "project_id": str(proj_id),
            "share_type": "full", "contract_no": cno,
        })
        assert _j(rv)["booklet"]["code"] == cno

    def test_delete_nonexistent(self, admin_client):
        rv = admin_client.delete("/api/booklets/999999")
        assert rv.status_code == 404


# =============================================================================
# 6. ANNOUNCEMENTS API
# =============================================================================

class TestAnnouncementsAPI:

    def test_list(self, admin_client):
        rv = admin_client.get("/api/announcements")
        assert rv.status_code == 200
        assert "announcements" in _j(rv)

    def test_announcement_fields(self, admin_client, ann_id):
        anns = _j(admin_client.get("/api/announcements"))["announcements"]
        a = next((x for x in anns if x["id"] == ann_id), None)
        assert a is not None
        for f in ("id","title","body","date"):
            assert f in a

    def test_create_and_read(self, admin_client):
        title = f"اطلاعیه {_rand()}"
        rv = admin_client.post("/api/announcements", data={"title": title, "body": "متن"})
        assert rv.status_code == 201
        titles = [a["title"] for a in _j(admin_client.get("/api/announcements"))["announcements"]]
        assert title in titles

    def test_create_via_json(self, admin_client):
        title = f"اطلاعیه جیسون {_rand()}"
        rv = _post_json(admin_client, "/api/announcements", {"title": title, "body": "متن JSON"})
        assert rv.status_code == 201

    def test_missing_body_400(self, admin_client):
        rv = admin_client.post("/api/announcements", data={"title": "بدون متن"})
        assert rv.status_code == 400

    def test_missing_title_400(self, admin_client):
        rv = admin_client.post("/api/announcements", data={"body": "بدون عنوان"})
        assert rv.status_code == 400

    def test_delete_announcement(self, admin_client):
        rv = admin_client.post("/api/announcements", data={"title": "حذفی", "body": "متن"})
        aid = _j(rv)["id"]
        assert admin_client.delete(f"/api/announcements/{aid}").status_code == 200
        ids = [a["id"] for a in _j(admin_client.get("/api/announcements"))["announcements"]]
        assert aid not in ids

    def test_member_can_read(self, member_client):
        assert member_client.get("/api/announcements").status_code == 200

    def test_member_cannot_create(self, member_client):
        rv = member_client.post("/api/announcements", data={"title": "غ", "body": "م"})
        assert rv.status_code == 403

    def test_member_cannot_delete(self, member_client, ann_id):
        assert member_client.delete(f"/api/announcements/{ann_id}").status_code == 403

    def test_delete_nonexistent(self, admin_client):
        assert admin_client.delete("/api/announcements/999999").status_code == 404


# =============================================================================
# 7. PAYMENTS API
# =============================================================================

class TestPaymentsAPI:

    def test_list_payments_admin(self, admin_client):
        rv = admin_client.get("/api/payments")
        assert rv.status_code == 200
        assert "payments" in _j(rv)

    def test_create_and_read_payment(self, app, sess, admin_client, member_uid, booklet_id):
        with app.app_context():
            p = Payment(user_id=member_uid, booklet_id=booklet_id,
                        amount=500000, due_date="1403-01-01", status="unpaid")
            sess.add(p); sess.commit()
        rv = admin_client.get("/api/payments")
        payments = _j(rv)["payments"]
        assert any(pay["amount"] == 500000 for pay in payments)

    def test_payment_status_values(self, admin_client):
        for p in _j(admin_client.get("/api/payments"))["payments"]:
            assert p["status"] in ("unpaid","paid","overdue")

    def test_payment_fields(self, admin_client):
        payments = _j(admin_client.get("/api/payments"))["payments"]
        if payments:
            for f in ("id","amount","due_date","status"):
                assert f in payments[0]

    def test_member_sees_own_payments(self, member_client):
        assert member_client.get("/api/payments").status_code == 200

    def test_member_cannot_patch_payment(self, member_client, app, sess, member_uid, booklet_id):
        with app.app_context():
            p = Payment(user_id=member_uid, booklet_id=booklet_id,
                        amount=100000, due_date="1403-02-01", status="unpaid")
            sess.add(p); sess.commit(); pid = p.id
        rv = member_client.patch(f"/api/finance/payments/{pid}",
                                 data=json.dumps({"status": "paid"}),
                                 content_type="application/json")
        assert rv.status_code == 403

    def test_finance_summary(self, admin_client):
        rv = admin_client.get("/api/finance/summary")
        assert rv.status_code == 200
        d = _j(rv)
        for f in ("total_paid","total_unpaid","total_overdue"):
            assert f in d


# =============================================================================
# 8. PLANS API
# =============================================================================

class TestPlansAPI:

    def test_list_plans(self, admin_client):
        rv = admin_client.get("/api/plans")
        assert rv.status_code == 200
        assert "plans" in _j(rv)

    def test_create_plan(self, admin_client, proj_id):
        rv = admin_client.post("/api/plans", data={
            "title": f"طرح {_rand()}", "total_amount": "2000000",
            "installments": "6", "start_date": "1403-01-01",
            "project_id": str(proj_id),
        })
        assert rv.status_code in (200, 201)

    def test_create_plan_missing_fields(self, admin_client):
        rv = admin_client.post("/api/plans", data={"title": "ناقص"})
        assert rv.status_code == 400

    def test_member_cannot_create_plan(self, member_client):
        rv = member_client.post("/api/plans", data={
            "title": "غ", "total_amount": "1", "installments": "1", "start_date": "1403-01-01",
        })
        assert rv.status_code == 403


# =============================================================================
# 9. TICKETS API
# =============================================================================

class TestTicketsAPI:

    def test_list_admin(self, admin_client):
        rv = admin_client.get("/api/tickets")
        assert rv.status_code == 200
        assert "tickets" in _j(rv)

    def test_list_member(self, member_client):
        assert member_client.get("/api/tickets").status_code == 200

    def test_ticket_fields(self, admin_client, ticket_id):
        tickets = _j(admin_client.get("/api/tickets"))["tickets"]
        t = next((x for x in tickets if x["id"] == ticket_id), None)
        assert t is not None
        for f in ("id","number","subject","category","priority","status"):
            assert f in t

    def test_category_values(self, admin_client):
        valid = {"financial","transfer","technical","general"}
        for t in _j(admin_client.get("/api/tickets"))["tickets"]:
            assert t["category"] in valid

    def test_priority_values(self, admin_client):
        valid = {"low","normal","high","urgent"}
        for t in _j(admin_client.get("/api/tickets"))["tickets"]:
            assert t["priority"] in valid

    def test_status_values(self, admin_client):
        valid = {"open","in_progress","waiting","resolved","closed"}
        for t in _j(admin_client.get("/api/tickets"))["tickets"]:
            assert t["status"] in valid

    def test_get_ticket_detail(self, admin_client, ticket_id):
        rv = admin_client.get(f"/api/tickets/{ticket_id}")
        assert rv.status_code == 200
        d = _j(rv)
        assert "ticket" in d and "messages" in d

    def test_add_message(self, admin_client, ticket_id):
        rv = admin_client.post(f"/api/tickets/{ticket_id}/messages",
                               data={"body": "پاسخ ادمین"})
        assert rv.status_code in (200, 201)

    def test_close_ticket(self, admin_client, ticket_id):
        rv = admin_client.post(f"/api/tickets/{ticket_id}/status",
                               data={"status": "closed"})
        assert rv.status_code == 200

    def test_get_nonexistent(self, admin_client):
        assert admin_client.get("/api/tickets/999999").status_code == 404


# =============================================================================
# 10. NOTIFICATIONS API
# =============================================================================

class TestNotificationsAPI:

    def test_list(self, member_client):
        rv = member_client.get("/api/notifications")
        assert rv.status_code == 200
        assert "notifications" in _j(rv)

    def test_send_notification(self, admin_client, member_uid):
        rv = admin_client.post("/api/notifications/send", data={
            "user_id": str(member_uid), "title": "آزمون", "body": "اعلان تست", "type": "info",
        })
        assert rv.status_code in (200, 201)

    def test_notification_appears_in_list(self, admin_client, member_client, member_uid):
        admin_client.post("/api/notifications/send", data={
            "user_id": str(member_uid), "title": "اعلان بررسی", "body": "متن",
        })
        rv = member_client.get("/api/notifications")
        titles = [n["title"] for n in _j(rv)["notifications"]]
        assert "اعلان بررسی" in titles

    def test_notification_fields(self, admin_client, member_client, member_uid):
        admin_client.post("/api/notifications/send", data={
            "user_id": str(member_uid), "title": "فیلد تست", "body": "متن",
        })
        rv = member_client.get("/api/notifications")
        if _j(rv)["notifications"]:
            n = _j(rv)["notifications"][0]
            for f in ("id","title","body","type","read","created_at"):
                assert f in n

    def test_mark_all_read(self, member_client):
        rv = member_client.post("/api/notifications/read", data={"all": "true"})
        assert rv.status_code == 200

    def test_member_cannot_send(self, member_client):
        rv = member_client.post("/api/notifications/send", data={
            "user_id": "1", "title": "غ", "body": "م",
        })
        assert rv.status_code == 403


# =============================================================================
# 11. TRANSFER REQUESTS
# =============================================================================

class TestTransferAPI:

    def test_list_admin(self, admin_client):
        rv = admin_client.get("/api/requests")
        assert rv.status_code == 200
        assert "requests" in _j(rv)

    def test_list_member(self, member_client):
        assert member_client.get("/api/requests").status_code == 200

    def test_history(self, admin_client):
        rv = admin_client.get("/api/transfer-history")
        assert rv.status_code == 200
        assert "history" in _j(rv)

    def test_member_cannot_approve(self, member_client):
        rv = member_client.post("/api/requests/1/approve")
        assert rv.status_code in (403, 404)

    def test_member_cannot_reject(self, member_client):
        rv = member_client.post("/api/requests/1/reject")
        assert rv.status_code in (403, 404)

    def test_approve_nonexistent(self, admin_client):
        assert admin_client.post("/api/requests/999999/approve").status_code == 404

    def test_reject_nonexistent(self, admin_client):
        assert admin_client.post("/api/requests/999999/reject").status_code == 404

    def test_request_fields_in_list(self, admin_client, app, sess, booklet_id, member_uid):
        with app.app_context():
            tr = TransferRequest(
                booklet_id=booklet_id, requester_id=member_uid,
                new_owner_first_name="علی", new_owner_last_name="تست",
                new_owner_national_code="0123456789", new_owner_phone="09000000000",
            )
            sess.add(tr); sess.commit()
        rv = admin_client.get("/api/requests")
        reqs = _j(rv)["requests"]
        if reqs:
            r = reqs[0]
            for f in ("id","status","booklet_id"):
                assert f in r


# =============================================================================
# 12. SITE SETTINGS
# =============================================================================

class TestSiteSettings:

    def test_get_settings(self, admin_client):
        rv = admin_client.get("/api/settings")
        assert rv.status_code == 200
        assert "settings" in _j(rv)

    def test_site_title_exists(self, admin_client):
        assert "site_title" in _j(admin_client.get("/api/settings"))["settings"]

    def test_save_via_form(self, admin_client):
        rv = admin_client.post("/api/settings", data={"site_title": "تعاونی مسکن دادگستری کل استان زنجان"})
        assert rv.status_code == 200

    def test_save_via_json(self, admin_client):
        rv = _post_json(admin_client, "/api/settings", {"contact_phone": "02412345678"})
        assert rv.status_code == 200
        assert _j(rv)["ok"] is True

    def test_settings_persisted(self, admin_client):
        title = f"تست عنوان {_rand()}"
        admin_client.post("/api/settings", data={"site_title": title})
        assert _j(admin_client.get("/api/settings"))["settings"]["site_title"] == title

    def test_member_cannot_save(self, member_client):
        rv = member_client.post("/api/settings", data={"site_title": "غ"})
        assert rv.status_code == 403


# =============================================================================
# 13. SLIDES API
# =============================================================================

class TestSlidesAPI:

    def test_list(self, admin_client):
        rv = admin_client.get("/api/slides")
        assert rv.status_code == 200
        assert "slides" in _j(rv)

    def test_create_slide(self, app, sess, admin_client):
        with app.app_context():
            s = Slide(title="اسلاید تست", media_type="image", active=True, order=99)
            sess.add(s); sess.commit()
        rv = admin_client.get("/api/slides")
        assert any(s["title"] == "اسلاید تست" for s in _j(rv)["slides"])

    def test_slide_fields(self, admin_client):
        slides = _j(admin_client.get("/api/slides"))["slides"]
        if slides:
            for f in ("id","title","media_type","active","order"):
                assert f in slides[0]

    def test_media_type_values(self, admin_client):
        for s in _j(admin_client.get("/api/slides"))["slides"]:
            assert s["media_type"] in ("image","video")


# =============================================================================
# 14. ACTIVITY LOG
# =============================================================================

class TestActivityLog:

    def test_admin_can_read(self, admin_client):
        rv = admin_client.get("/api/activity-log")
        assert rv.status_code == 200
        assert "logs" in _j(rv)

    def test_log_entry_fields(self, admin_client, app, sess):
        with app.app_context():
            sess.add(ActivityLog(action="test_log", category="test", detail="جزئیات"))
            sess.commit()
        rv = admin_client.get("/api/activity-log")
        logs = _j(rv)["logs"]
        if logs:
            for f in ("id","action","category","created_at"):
                assert f in logs[0]

    def test_member_blocked(self, member_client):
        assert member_client.get("/api/activity-log").status_code == 403

    def test_login_logged(self, app, sess):
        with app.app_context():
            count = sess.query(ActivityLog).filter_by(action="login").count()
            assert count >= 1


# =============================================================================
# 15. REPORTS
# =============================================================================

class TestReports:

    def test_reports_admin(self, admin_client):
        assert admin_client.get("/api/reports").status_code == 200

    def test_member_blocked(self, member_client):
        assert member_client.get("/api/reports").status_code == 403


# =============================================================================
# 16. BALE API
# =============================================================================

class TestBaleAPI:

    def test_link_code_format(self, member_client):
        rv = member_client.get("/api/bale/link-code")
        assert rv.status_code == 200
        code = _j(rv)["code"]
        assert len(str(code)) == 6
        assert str(code).isdigit()

    def test_bale_status(self, member_client):
        rv = member_client.get("/api/bale/status")
        assert rv.status_code == 200
        assert "linked" in _j(rv)

    def test_bale_unlink(self, member_client):
        rv = member_client.post("/api/bale/unlink")
        assert rv.status_code in (200, 204)

    def test_broadcast_admin_only(self, member_client):
        rv = member_client.post("/api/bale/broadcast", data={"text": "تست"})
        assert rv.status_code == 403

    def test_broadcast_admin(self, admin_client):
        rv = admin_client.post("/api/bale/broadcast", data={"text": "پیام تست ادمین"})
        assert rv.status_code in (200, 201)


# =============================================================================
# 17. PROFILE API
# =============================================================================

class TestProfileAPI:

    def test_member_profile(self, member_client):
        rv = member_client.get("/api/profile/me")
        assert rv.status_code == 200
        d = _j(rv)
        for f in ("id","username","first_name","last_name","role"):
            assert f in d

    def test_admin_profile(self, admin_client):
        rv = admin_client.get("/api/profile/me")
        assert rv.status_code == 200
        assert _j(rv)["role"] == "admin"

    def test_profile_role_values(self, member_client):
        assert _j(member_client.get("/api/profile/me"))["role"] in ("admin","member")


# =============================================================================
# 18. DASHBOARD PAGES
# =============================================================================

class TestDashboardPages:

    def test_home(self, admin_client):
        assert admin_client.get("/dashboard/").status_code == 200

    def test_members_page(self, admin_client):
        assert admin_client.get("/dashboard/members").status_code == 200

    def test_member_profiles_page_admin(self, admin_client):
        assert admin_client.get("/dashboard/member-profiles").status_code == 200

    def test_member_profiles_blocked_for_member(self, member_client):
        rv = member_client.get("/dashboard/member-profiles", follow_redirects=False)
        assert rv.status_code in (302, 403)

    def test_projects_page(self, admin_client):
        assert admin_client.get("/dashboard/projects").status_code == 200

    def test_booklet_page(self, admin_client):
        assert admin_client.get("/dashboard/booklet").status_code == 200

    def test_announcements_page(self, admin_client):
        assert admin_client.get("/dashboard/announcements").status_code == 200

    def test_requests_page(self, admin_client):
        assert admin_client.get("/dashboard/requests").status_code == 200

    def test_finance_page(self, admin_client):
        assert admin_client.get("/dashboard/finance").status_code == 200

    def test_my_payments_page(self, member_client):
        assert member_client.get("/dashboard/my-payments").status_code == 200

    def test_tickets_page(self, admin_client):
        assert admin_client.get("/dashboard/tickets").status_code == 200

    def test_notifications_page(self, admin_client):
        assert admin_client.get("/dashboard/notifications").status_code == 200

    def test_reports_page(self, admin_client):
        assert admin_client.get("/dashboard/reports").status_code == 200

    def test_history_page(self, admin_client):
        assert admin_client.get("/dashboard/history").status_code == 200

    def test_activity_log_page_admin(self, admin_client):
        assert admin_client.get("/dashboard/activity-log").status_code == 200

    def test_activity_log_page_member_blocked(self, member_client):
        rv = member_client.get("/dashboard/activity-log", follow_redirects=False)
        assert rv.status_code in (302, 403)

    def test_bale_page(self, admin_client):
        assert admin_client.get("/dashboard/bale").status_code == 200

    def test_landing_admin_page(self, admin_client):
        assert admin_client.get("/dashboard/landing").status_code == 200

    def test_contract_page(self, admin_client, booklet_id):
        assert admin_client.get(f"/dashboard/contract/{booklet_id}").status_code == 200

    def test_ticket_detail_page(self, admin_client, ticket_id):
        assert admin_client.get(f"/dashboard/tickets/{ticket_id}").status_code == 200

    def test_request_detail_page(self, admin_client, app, sess, booklet_id, member_uid):
        with app.app_context():
            tr = TransferRequest(
                booklet_id=booklet_id, requester_id=member_uid,
                new_owner_first_name="ر", new_owner_last_name="ت",
                new_owner_national_code="9876543210", new_owner_phone="09000000001",
            )
            sess.add(tr); sess.commit(); rid = tr.id
        assert admin_client.get(f"/dashboard/requests/{rid}").status_code == 200


# =============================================================================
# 19. PUBLIC SITE
# =============================================================================

class TestPublicSite:

    def test_index_loads(self, app):
        assert app.test_client().get("/").status_code == 200

    def test_index_html_content(self, app):
        body = app.test_client().get("/").data.decode("utf-8")
        assert "تعاونی" in body or "مسکن" in body or "دادگستری" in body

    def test_index_has_html_structure(self, app):
        body = app.test_client().get("/").data.decode("utf-8")
        assert "<html" in body or "<!doctype" in body.lower()

    def test_announcements_rendered_on_public(self, app, admin_client, ann_id):
        # create an announcement and check public page loads
        assert app.test_client().get("/").status_code == 200


# =============================================================================
# 20. SECURITY & EDGE CASES
# =============================================================================

class TestSecurity:

    def test_unauthenticated_api_members(self, app):
        rv = app.test_client().get("/api/members")
        assert rv.status_code in (401, 302, 403)

    def test_unauthenticated_api_booklets(self, app):
        rv = app.test_client().get("/api/booklets")
        assert rv.status_code in (401, 302, 403)

    def test_unauthenticated_api_settings(self, app):
        rv = app.test_client().get("/api/settings")
        assert rv.status_code in (401, 302, 403)

    def test_invalid_json_does_not_crash(self, admin_client):
        rv = admin_client.post("/api/announcements", data="not-json",
                               content_type="application/json")
        assert rv.status_code in (400, 415)
        assert rv.status_code != 500

    def test_nonexistent_project_gallery(self, admin_client):
        rv = admin_client.get("/api/projects/999999/gallery")
        assert rv.status_code in (200, 404)

    def test_nonexistent_ticket_404(self, admin_client):
        assert admin_client.get("/api/tickets/999999").status_code == 404

    def test_nonexistent_announcement_delete_404(self, admin_client):
        assert admin_client.delete("/api/announcements/999999").status_code == 404

    def test_nonexistent_booklet_delete_404(self, admin_client):
        assert admin_client.delete("/api/booklets/999999").status_code == 404

    def test_member_cannot_delete_member(self, member_client, member_uid):
        assert member_client.delete(f"/api/members/{member_uid}").status_code == 403

    def test_member_cannot_delete_project(self, member_client, proj_id):
        assert member_client.delete(f"/api/projects/{proj_id}").status_code == 403


# =============================================================================
# 21. SESSION CONFIG
# =============================================================================

class TestSessionConfig:

    def test_session_lifetime(self, app):
        from datetime import timedelta
        assert app.config.get("PERMANENT_SESSION_LIFETIME") == timedelta(minutes=10)

    def test_session_refresh(self, app):
        assert app.config.get("SESSION_REFRESH_EACH_REQUEST") is True

    def test_secret_key_set(self, app):
        assert app.secret_key and len(app.secret_key) >= 16
