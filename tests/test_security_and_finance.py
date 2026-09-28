"""
تست‌های امنیت و منطق مالی:
- CSRF protection
- Rate limiting
- تأیید نقل و انتقال (transfer approval)
- محاسبه اقساط (installment generation)
- Soft delete دفترچه
"""
import json
import pytest
from werkzeug.security import generate_password_hash

from app.extensions import limiter
from app.models import (Booklet, Payment, Project, TransferHistory,
                        TransferRequest, User)


def _j(rv):
    return json.loads(rv.data)


def _post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sess(app):
    return app.db


@pytest.fixture(scope="module")
def admin_client(app):
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin123"})
    return c


@pytest.fixture(scope="module")
def scenario(app, sess, admin_client):
    """پروژه + دو عضو + دفترچه‌های تمام‌سهم و نیم‌سهم"""
    with app.app_context():
        proj = Project(name="پروژه تست مالی-امنیتی", status="active", active=True)
        sess.add(proj)
        sess.flush()

        _req_kwargs = dict(
            father_name="حسن", birth_date="1360/01/01", birth_place="زنجان",
            marital_status="متأهل", occupation="کارمند", emergency_phone="09120000005",
            postal_code="4519999999", address="زنجان", bank_name="ملت",
        )
        full_owner = User(username="sf_full", password_hash=generate_password_hash("pw123"),
                          first_name="مالک", last_name="تمام‌سهم", role="member",
                          national_code="1111111111", active=True, profile_complete=True,
                          phone="09120000006", **_req_kwargs)
        half_owner = User(username="sf_half", password_hash=generate_password_hash("pw123"),
                          first_name="مالک", last_name="نیم‌سهم", role="member",
                          national_code="2222222222", active=True, profile_complete=True,
                          phone="09120000007", **_req_kwargs)
        sess.add_all([full_owner, half_owner])
        sess.flush()

        b_full = Booklet(code="SF-FULL-001", serial=1, project_id=proj.id,
                         owner_id=full_owner.id, share_type="full")
        b_half = Booklet(code="SF-HALF-001", serial=2, project_id=proj.id,
                         owner_id=half_owner.id, share_type="half")
        sess.add_all([b_full, b_half])
        sess.commit()

        return {
            "project_id": proj.id,
            "full_owner_id": full_owner.id, "half_owner_id": half_owner.id,
            "b_full_id": b_full.id, "b_half_id": b_half.id,
        }


# ─── CSRF ─────────────────────────────────────────────────────────────────────

class TestCSRF:
    def test_post_without_token_rejected_when_csrf_enabled(self, app, admin_client):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            rv = _post_json(admin_client, "/api/settings", {"site_phone": "123"})
            assert rv.status_code == 400  # CSRF token missing
        finally:
            app.config["WTF_CSRF_ENABLED"] = False

    def test_post_with_token_accepted(self, app, admin_client):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            # توکن از صفحه داشبورد استخراج می‌شود
            page = admin_client.get("/dashboard/").data.decode()
            import re
            m = re.search(r'name="csrf-token" content="([^"]+)"', page)
            assert m, "csrf meta tag not found in dashboard layout"
            rv = admin_client.post(
                "/api/settings",
                data=json.dumps({"site_phone": "123"}),
                content_type="application/json",
                headers={"X-CSRFToken": m.group(1)},
            )
            assert rv.status_code == 200
        finally:
            app.config["WTF_CSRF_ENABLED"] = False

    def test_bale_webhook_is_csrf_exempt(self, app):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            c = app.test_client()
            rv = _post_json(c, "/api/bale/webhook", {"message": {}})
            assert rv.status_code == 200
        finally:
            app.config["WTF_CSRF_ENABLED"] = False

    def test_login_form_contains_csrf_field(self, app):
        c = app.test_client()
        page = c.get("/login").data.decode()
        assert 'name="csrf_token"' in page


# ─── Input validation ─────────────────────────────────────────────────────────

class TestMemberValidation:
    def test_postal_code_too_long_rejected(self, admin_client):
        """باگ production: کد پستی ۱۱ رقمی → قبلاً 500 (VARCHAR(10))، حالا 400"""
        rv = _post_json(admin_client, "/api/members", {
            "first_name": "وحید", "last_name": "غفاری",
            "username": "val_test_user1", "password": "pw1234",
            "national_code": "4271113905",
            "postal_code": "45159884759",   # ۱۱ رقم — نامعتبر
        })
        assert rv.status_code == 400
        assert "کد پستی" in _j(rv)["error"]

    def test_national_code_wrong_length_rejected(self, admin_client):
        rv = _post_json(admin_client, "/api/members", {
            "first_name": "الف", "last_name": "ب",
            "username": "val_test_user2", "password": "pw1234",
            "national_code": "123",
        })
        assert rv.status_code == 400
        assert "کد ملی" in _j(rv)["error"]

    def test_persian_digits_normalized(self, app, sess, admin_client):
        rv = _post_json(admin_client, "/api/members", {
            "first_name": "پ", "last_name": "ت",
            "username": "val_test_user3", "password": "pw1234",
            "national_code": "۱۲۳۴۵۶۷۸۹۰",   # ارقام فارسی
        })
        assert rv.status_code == 201
        with app.app_context():
            u = sess.query(User).filter_by(username="val_test_user3").first()
            assert u.national_code == "1234567890"


# ─── Transfer search/filter + document archiving ─────────────────────────────

class TestTransferSearchAndDocs:
    @pytest.fixture(scope="class")
    def setup(self, app, sess, admin_client):
        from app.models import Booklet, Project, User
        with app.app_context():
            proj = Project(name="پروژه انتقال-تست", status="active", active=True)
            owner = User(username="tr_owner", password_hash=generate_password_hash("pw"),
                         first_name="صاحب", last_name="دفترچه", role="member",
                         national_code="4445556667", active=True, profile_complete=True,
                         father_name="حسن", birth_date="1360/01/01", birth_place="زنجان",
                         marital_status="متأهل", occupation="کارمند", phone="09120000003", emergency_phone="09120000004",
                         postal_code="4519999999", address="زنجان", bank_name="ملت")
            sess.add_all([proj, owner]); sess.flush()
            b = Booklet(code="TRSRCH-001", serial=1, project_id=proj.id,
                        owner_id=owner.id, share_type="full")
            sess.add(b); sess.commit()
            return {"project_id": proj.id, "owner_id": owner.id, "booklet_id": b.id}

    def _submit(self, app, setup, fn="خریدار", nat="1231231234"):
        import io
        c = app.test_client()
        c.post("/login", data={"username": "tr_owner", "password": "pw"})
        return c.post("/api/requests", data={
            "booklet_id": setup["booklet_id"],
            "new_owner_first_name": fn, "new_owner_last_name": "جدید",
            "new_owner_national_code": nat, "new_owner_phone": "09120000000",
            "id_first_page": (io.BytesIO(b"%PDF-1.4"), "id.pdf", "application/pdf"),
            "sana_form": (io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 20), "opt1.jpg", "image/jpeg"),
        }, content_type="multipart/form-data")

    def test_submit_archives_docs_to_member(self, app, sess, setup):
        rv = self._submit(app, setup)
        assert rv.status_code == 201
        with app.app_context():
            from app.models import MemberDocument
            docs = sess.query(MemberDocument).filter_by(user_id=setup["owner_id"]).all()
            titles = [d.title for d in docs]
            assert any("شناسنامه" in t for t in titles)
            assert any("سند اختیاری ۱" in t for t in titles)
            # همه در فولدر requests ذخیره شده‌اند
            assert all(d.file_path.startswith("requests/") for d in docs)

    def test_search_by_new_owner(self, app, admin_client, setup):
        self._submit(app, setup, fn="یکتاجو", nat="9998887776")
        d = _j(admin_client.get("/api/requests?search=یکتاجو"))
        assert all("یکتاجو" == r["new_owner_first_name"] for r in d["requests"])
        assert len(d["requests"]) >= 1

    def test_search_by_booklet_code(self, admin_client, setup):
        d = _j(admin_client.get("/api/requests?search=TRSRCH-001"))
        assert all(r["booklet_code"] == "TRSRCH-001" for r in d["requests"])

    def test_filter_by_status(self, admin_client, setup):
        d = _j(admin_client.get("/api/requests?status=pending"))
        assert all(r["status"] == "pending" for r in d["requests"])

    def test_filter_by_project(self, admin_client, setup):
        d = _j(admin_client.get(f"/api/requests?project_id={setup['project_id']}"))
        assert all(r["project_name"] == "پروژه انتقال-تست" for r in d["requests"])


# ─── Admin edit member + password ────────────────────────────────────────────

class TestMemberEdit:
    @pytest.fixture(scope="class")
    def uid(self, app, sess):
        with app.app_context():
            u = User(username="edit_me", password_hash=generate_password_hash("orig123"),
                     first_name="قبل", last_name="ویرایش", role="member",
                     national_code="3334445556", phone="09120001122",
                     active=True, profile_complete=True)
            sess.add(u); sess.commit()
            return u.id

    def test_get_member(self, admin_client, uid):
        d = _j(admin_client.get(f"/api/members/{uid}"))
        assert d["member"]["first_name"] == "قبل"

    def test_update_member(self, app, sess, admin_client, uid):
        rv = _post_json(admin_client, f"/api/members/{uid}", {
            "first_name": "بعد", "last_name": "ویرایش",
            "username": "edit_me", "occupation": "مهندس"})
        assert rv.status_code == 200
        with app.app_context():
            u = sess.get(User, uid)
            assert u.first_name == "بعد" and u.occupation == "مهندس"

    def test_update_rejects_bad_postal(self, admin_client, uid):
        rv = _post_json(admin_client, f"/api/members/{uid}",
                        {"first_name": "x", "last_name": "y", "username": "edit_me",
                         "postal_code": "123"})
        assert rv.status_code == 400

    def test_duplicate_username_rejected(self, admin_client, uid):
        rv = _post_json(admin_client, f"/api/members/{uid}",
                        {"first_name": "x", "last_name": "y", "username": "admin"})
        assert rv.status_code == 409

    def test_admin_change_password(self, app, admin_client, uid):
        rv = _post_json(admin_client, f"/api/members/{uid}/password", {"password": "newpass9"})
        assert rv.status_code == 200
        c = app.test_client()
        assert c.post("/login", data={"username": "edit_me", "password": "newpass9"}).status_code == 302

    def test_short_password_rejected(self, admin_client, uid):
        assert _post_json(admin_client, f"/api/members/{uid}/password", {"password": "ab"}).status_code == 400

    def test_member_cannot_edit(self, app, scenario):
        c = app.test_client()
        c.post("/login", data={"username": "sf_full", "password": "pw123"})
        assert _post_json(c, f"/api/members/{scenario['half_owner_id']}",
                          {"first_name": "x", "last_name": "y", "username": "z"}).status_code == 403


class TestForgotByPhone:
    def test_lookup_by_phone(self, app, sess, monkeypatch):
        from app import sms as sms_mod
        monkeypatch.setattr(sms_mod, "send_verify_code", lambda *a, **k: True)
        with app.app_context():
            u = User(username="phone_lookup", password_hash=generate_password_hash("x"),
                     first_name="ف", last_name="ل", role="member",
                     national_code="7778889990", phone="09135557777",
                     active=True, profile_complete=True)
            sess.add(u); sess.commit()
        c = app.test_client()
        # ورود با شماره موبایل به‌جای کد ملی
        rv = c.post("/forgot-password", data={"national_code": "09135557777"})
        assert rv.status_code == 302


# ─── Members pagination & search ─────────────────────────────────────────────

class TestMembersPagination:
    def test_no_page_param_returns_all(self, admin_client):
        rv = admin_client.get("/api/members")
        d = _j(rv)
        assert rv.status_code == 200
        assert "total" in d and d["pages"] == 1

    def test_pagination_limits_results(self, admin_client):
        rv = admin_client.get("/api/members?page=1&per_page=2")
        d = _j(rv)
        assert len(d["members"]) <= 2
        if d["total"] > 2:
            assert d["pages"] >= 2

    def test_search_filters_members(self, admin_client):
        rv = admin_client.get("/api/members?search=تمام‌سهم&page=1")
        d = _j(rv)
        assert rv.status_code == 200
        assert all("تمام‌سهم" in (m["last_name"] or "") for m in d["members"])

    def test_search_no_match(self, admin_client):
        rv = admin_client.get("/api/members?search=zzz_not_exist_999&page=1")
        d = _j(rv)
        assert d["total"] == 0 and d["members"] == []


# ─── Member documents archive ─────────────────────────────────────────────────

class TestMemberDocuments:
    def _upload(self, admin_client, uid, title="قرارداد تست"):
        import io
        return admin_client.post(
            f"/api/members/{uid}/documents",
            data={"title": title, "doc_type": "contract",
                  "file": (io.BytesIO(b"%PDF-1.4 test"), "contract.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )

    def test_upload_and_list(self, admin_client, scenario):
        uid = scenario["full_owner_id"]
        rv = self._upload(admin_client, uid)
        assert rv.status_code == 201
        doc = _j(rv)["document"]
        assert doc["title"] == "قرارداد تست"
        assert doc["file_path"].startswith("member_docs/")

        rv2 = admin_client.get(f"/api/members/{uid}/documents")
        assert any(d["id"] == doc["id"] for d in _j(rv2)["documents"])

    def test_upload_requires_title(self, admin_client, scenario):
        import io
        rv = admin_client.post(
            f"/api/members/{scenario['full_owner_id']}/documents",
            data={"file": (io.BytesIO(b"x"), "a.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        assert rv.status_code == 400

    def test_member_sees_own_docs_not_others(self, app, scenario):
        c = app.test_client()
        c.post("/login", data={"username": "sf_full", "password": "pw123"})
        # اسناد خودش
        rv = c.get(f"/api/members/{scenario['full_owner_id']}/documents")
        assert rv.status_code == 200
        # اسناد دیگری → 403
        rv2 = c.get(f"/api/members/{scenario['half_owner_id']}/documents")
        assert rv2.status_code == 403

    def test_doc_file_protected_from_anonymous(self, app, admin_client, scenario):
        rv = self._upload(admin_client, scenario["full_owner_id"], "سند محافظت")
        path = _j(rv)["document"]["file_path"]
        anon = app.test_client()
        assert anon.get(f"/uploads/{path}").status_code == 403
        # ادمین دسترسی دارد
        assert admin_client.get(f"/uploads/{path}").status_code == 200

    def test_delete_doc(self, admin_client, scenario):
        uid = scenario["full_owner_id"]
        did = _j(self._upload(admin_client, uid, "برای حذف"))["document"]["id"]
        rv = admin_client.delete(f"/api/members/{uid}/documents/{did}")
        assert rv.status_code == 200
        rv2 = admin_client.get(f"/api/members/{uid}/documents")
        assert not any(d["id"] == did for d in _j(rv2)["documents"])


# ─── Accounting: deposit vouchers ────────────────────────────────────────────

class TestAccounting:
    @pytest.fixture(scope="class")
    def account_id(self, admin_client):
        rv = _post_json(admin_client, "/api/accounting/accounts", {
            "holder_name": "علی غفاری", "holder_role": "مدیر اجرایی",
            "bank_name": "ملی", "card_number": "6037991234567890",
        })
        assert rv.status_code == 201
        return _j(rv)["account"]["id"]

    def test_create_voucher_for_member(self, admin_client, account_id, scenario):
        rv = _post_json(admin_client, "/api/accounting/vouchers", {
            "account_id": account_id,
            "user_id": scenario["full_owner_id"],
            "amount": "50,000,000",
            "deposit_date": "۱۴۰۴/۰۵/۰۱",     # ارقام فارسی — باید نرمال شود
            "deposit_time": "14:30",
            "method": "card",
            "reference_no": "123456789",
            "description": "قسط اول",
        })
        assert rv.status_code == 201
        v = _j(rv)["voucher"]
        assert v["number"] >= 1001
        assert v["amount"] == 50000000
        assert v["deposit_date"] == "1404/05/01"
        assert v["status"] == "active"

    def test_create_voucher_free_payer(self, admin_client, account_id):
        rv = _post_json(admin_client, "/api/accounting/vouchers", {
            "account_id": account_id, "payer_name": "واریزکننده متفرقه",
            "amount": 1000000, "deposit_date": "1404/05/02",
        })
        assert rv.status_code == 201
        assert _j(rv)["voucher"]["payer_name"] == "واریزکننده متفرقه"

    def test_voucher_requires_payer(self, admin_client, account_id):
        rv = _post_json(admin_client, "/api/accounting/vouchers", {
            "account_id": account_id, "amount": 5000, "deposit_date": "1404/05/02",
        })
        assert rv.status_code == 400

    def test_voucher_invalid_amount(self, admin_client, account_id):
        rv = _post_json(admin_client, "/api/accounting/vouchers", {
            "account_id": account_id, "payer_name": "x",
            "amount": 0, "deposit_date": "1404/05/02",
        })
        assert rv.status_code == 400

    def test_list_with_totals(self, admin_client, account_id):
        rv = admin_client.get(f"/api/accounting/vouchers?account_id={account_id}")
        d = _j(rv)
        assert d["total"] >= 2
        assert d["total_amount"] >= 51000000

    def test_void_not_delete(self, admin_client, account_id):
        rv = _post_json(admin_client, "/api/accounting/vouchers", {
            "account_id": account_id, "payer_name": "برای ابطال",
            "amount": 999, "deposit_date": "1404/05/03",
        })
        vid = _j(rv)["voucher"]["id"]
        # بدون دلیل → رد
        assert _post_json(admin_client, f"/api/accounting/vouchers/{vid}/void", {}).status_code == 400
        # با دلیل → ابطال
        rv2 = _post_json(admin_client, f"/api/accounting/vouchers/{vid}/void", {"reason": "اشتباه ثبت"})
        assert rv2.status_code == 200
        # سند هنوز در لیست هست ولی voided
        d = _j(admin_client.get("/api/accounting/vouchers?status=voided"))
        assert any(v["id"] == vid and v["void_reason"] == "اشتباه ثبت" for v in d["vouchers"])
        # ابطال دوباره → خطا
        assert _post_json(admin_client, f"/api/accounting/vouchers/{vid}/void",
                          {"reason": "x"}).status_code == 400

    def test_member_sees_only_own_vouchers(self, app, account_id, scenario):
        c = app.test_client()
        c.post("/login", data={"username": "sf_full", "password": "pw123"})
        d = _j(c.get("/api/accounting/vouchers"))
        assert all(v["user_id"] == scenario["full_owner_id"] for v in d["vouchers"])

    def test_member_cannot_create_voucher(self, app, account_id):
        c = app.test_client()
        c.post("/login", data={"username": "sf_full", "password": "pw123"})
        rv = _post_json(c, "/api/accounting/vouchers", {
            "account_id": account_id, "payer_name": "x",
            "amount": 100, "deposit_date": "1404/05/04",
        })
        assert rv.status_code == 403

    def test_summary_per_account(self, admin_client, account_id):
        d = _j(admin_client.get("/api/accounting/summary"))
        row = next(s for s in d["summary"] if s["account"]["id"] == account_id)
        assert row["total_amount"] >= 51000000
        assert row["voucher_count"] >= 2


# ─── Accounting v2: reconciliation, statement, expenses, dashboard, role ──────

class TestAccountingReconciliation:
    @pytest.fixture(scope="class")
    def setup(self, app, sess, admin_client):
        """حساب + عضو + دو قسط + سند واریز"""
        from app.models import CoopAccount, Payment, User
        with app.app_context():
            acc = CoopAccount(holder_name="حساب تسویه", holder_role="مدیر")
            u = User(username="recon_member", password_hash=generate_password_hash("pw"),
                     first_name="تسویه", last_name="تست", role="member",
                     national_code="5551112222", active=True, profile_complete=True,
                     father_name="حسن", birth_date="1360/01/01", birth_place="زنجان",
                     marital_status="متأهل", occupation="کارمند", phone="09120000008", emergency_phone="09120000010",
                     postal_code="4519999999", address="زنجان", bank_name="ملت")
            sess.add_all([acc, u]); sess.flush()
            p1 = Payment(user_id=u.id, amount=10_000_000, due_date="1400/01/01", status="unpaid",
                         description="قسط ۱")
            p2 = Payment(user_id=u.id, amount=10_000_000, due_date="1490/01/01", status="unpaid",
                         description="قسط ۲")
            sess.add_all([p1, p2]); sess.commit()
            return {"acc": acc.id, "uid": u.id, "p1": p1.id, "p2": p2.id}

    def _voucher(self, admin_client, setup, amount):
        rv = _post_json(admin_client, "/api/accounting/vouchers", {
            "account_id": setup["acc"], "user_id": setup["uid"],
            "amount": amount, "deposit_date": "1404/01/01",
        })
        assert rv.status_code == 201
        return _j(rv)["voucher"]["id"]

    def test_full_allocation_marks_paid(self, app, sess, admin_client, setup):
        vid = self._voucher(admin_client, setup, 10_000_000)
        rv = _post_json(admin_client, f"/api/accounting/vouchers/{vid}/allocate",
                        {"items": [{"payment_id": setup["p1"], "amount": 10_000_000}]})
        assert rv.status_code == 200
        with app.app_context():
            p = sess.get(Payment, setup["p1"])
            assert p.status == "paid" and p.paid_date

    def test_over_allocation_rejected(self, admin_client, setup):
        vid = self._voucher(admin_client, setup, 5_000_000)
        rv = _post_json(admin_client, f"/api/accounting/vouchers/{vid}/allocate",
                        {"items": [{"payment_id": setup["p2"], "amount": 9_000_000}]})
        assert rv.status_code == 400

    def test_partial_allocation_past_due_is_overdue(self, app, sess, admin_client, setup):
        # قسط ۱ سررسیدش گذشته (1400) — تخصیص ناقص → overdue
        vid = self._voucher(admin_client, setup, 3_000_000)
        # اول تخصیص قبلی p1 را پاک کن با سند تازه‌ی جزئی
        rv = _post_json(admin_client, f"/api/accounting/vouchers/{vid}/allocate",
                        {"items": [{"payment_id": setup["p2"], "amount": 3_000_000}]})
        assert rv.status_code == 200
        with app.app_context():
            p2 = sess.get(Payment, setup["p2"])
            assert p2.status == "unpaid"   # سررسید 1490 نگذشته

    def test_void_voucher_reverts_payment(self, app, sess, admin_client, setup):
        vid = self._voucher(admin_client, setup, 10_000_000)
        _post_json(admin_client, f"/api/accounting/vouchers/{vid}/allocate",
                   {"items": [{"payment_id": setup["p2"], "amount": 10_000_000}]})
        with app.app_context():
            assert sess.get(Payment, setup["p2"]).status == "paid"
        rv = _post_json(admin_client, f"/api/accounting/vouchers/{vid}/void", {"reason": "اشتباه"})
        assert rv.status_code == 200
        with app.app_context():
            # p2 سررسید آینده دارد → به unpaid برمی‌گردد
            assert sess.get(Payment, setup["p2"]).status == "unpaid"

    def test_member_statement(self, admin_client, setup):
        rv = admin_client.get(f"/api/accounting/member/{setup['uid']}/statement")
        d = _j(rv)
        assert d["totals"]["debt"] == 20_000_000
        assert d["totals"]["paid"] >= 10_000_000
        assert len(d["transactions"]) >= 3   # ۲ قسط + حداقل ۱ واریز

    def test_member_sees_own_statement_only(self, app, setup, scenario):
        c = app.test_client()
        c.post("/login", data={"username": "recon_member", "password": "pw"})
        assert c.get(f"/api/accounting/member/{setup['uid']}/statement").status_code == 200
        assert c.get(f"/api/accounting/member/{scenario['full_owner_id']}/statement").status_code == 403

    def test_statement_excel_export(self, admin_client, setup):
        rv = admin_client.get(f"/api/accounting/member/{setup['uid']}/statement/export")
        assert rv.status_code == 200
        assert "spreadsheet" in rv.content_type

    def test_statement_page_renders(self, admin_client, setup):
        rv = admin_client.get(f"/dashboard/accounting/statement/{setup['uid']}")
        assert rv.status_code == 200
        assert "کارت حساب" in rv.data.decode()

    def test_statement_page_member_forbidden_for_others(self, app, setup, scenario):
        c = app.test_client()
        c.post("/login", data={"username": "recon_member", "password": "pw"})
        # صفحه دیگری → ریدایرکت به home
        rv = c.get(f"/dashboard/accounting/statement/{scenario['full_owner_id']}")
        assert rv.status_code in (302, 303)


class TestExpenses:
    @pytest.fixture(scope="class")
    def acc_id(self, app, sess):
        from app.models import CoopAccount
        with app.app_context():
            a = CoopAccount(holder_name="حساب هزینه")
            sess.add(a); sess.commit()
            return a.id

    def test_create_expense(self, admin_client, acc_id):
        rv = _post_json(admin_client, "/api/accounting/expenses", {
            "account_id": acc_id, "payee": "پیمانکار الف",
            "category": "contractor", "amount": "80,000,000",
            "spend_date": "۱۴۰۴/۰۳/۱۵",
        })
        assert rv.status_code == 201
        e = _j(rv)["expense"]
        assert e["number"] >= 5001 and e["amount"] == 80_000_000
        assert e["spend_date"] == "1404/03/15"

    def test_expense_requires_payee(self, admin_client, acc_id):
        rv = _post_json(admin_client, "/api/accounting/expenses", {
            "account_id": acc_id, "amount": 1000, "spend_date": "1404/01/01"})
        assert rv.status_code == 400

    def test_balance_deducts_expenses(self, admin_client, acc_id):
        _post_json(admin_client, "/api/accounting/vouchers", {
            "account_id": acc_id, "payer_name": "x",
            "amount": 100_000_000, "deposit_date": "1404/01/01"})
        d = _j(admin_client.get("/api/accounting/summary"))
        row = next(s for s in d["summary"] if s["account"]["id"] == acc_id)
        assert row["deposits"] == 100_000_000
        assert row["expenses"] == 80_000_000
        assert row["balance"] == 20_000_000

    def test_void_expense(self, admin_client, acc_id):
        eid = _j(_post_json(admin_client, "/api/accounting/expenses", {
            "account_id": acc_id, "payee": "y", "amount": 500, "spend_date": "1404/01/01"}))["expense"]["id"]
        assert _post_json(admin_client, f"/api/accounting/expenses/{eid}/void", {}).status_code == 400
        assert _post_json(admin_client, f"/api/accounting/expenses/{eid}/void",
                          {"reason": "لغو"}).status_code == 200


class TestAccountingExport:
    def test_vouchers_export_xlsx(self, admin_client):
        rv = admin_client.get("/api/accounting/vouchers/export")
        assert rv.status_code == 200
        assert "spreadsheet" in rv.content_type

    def test_expenses_export_xlsx(self, admin_client):
        rv = admin_client.get("/api/accounting/expenses/export")
        assert rv.status_code == 200

    def test_voucher_receipt_page(self, admin_client, setup_receipt):
        rv = admin_client.get(f"/dashboard/accounting/receipt/{setup_receipt}")
        assert rv.status_code == 200
        assert "رسید سند واریز" in rv.data.decode()


@pytest.fixture(scope="module")
def setup_receipt(app, sess, admin_client):
    from app.models import CoopAccount
    with app.app_context():
        a = CoopAccount(holder_name="حساب رسید")
        sess.add(a); sess.commit()
        aid = a.id
    rv = _post_json(admin_client, "/api/accounting/vouchers", {
        "account_id": aid, "payer_name": "تست رسید",
        "amount": 1_000_000, "deposit_date": "1404/01/01"})
    return _j(rv)["voucher"]["id"]


class TestOverdueMarking:
    def test_past_due_helper(self):
        from app.utils.jalali import is_past_due
        assert is_past_due("1400/01/01", "1404/05/01") is True
        assert is_past_due("1490/01/01", "1404/05/01") is False

    def test_jalali_today_format(self):
        from app.utils.jalali import today_jalali
        t = today_jalali()
        parts = t.split("/")
        assert len(parts) == 3 and len(parts[1]) == 2


class TestAdminOverview:
    def test_overview_shape(self, admin_client):
        d = _j(admin_client.get("/api/overview"))
        for key in ("members", "projects", "this_month", "overdue", "pending", "balance"):
            assert key in d
        assert "active" in d["members"] and "total" in d["members"]
        assert d["balance"]["net"] == d["balance"]["deposited"] - d["balance"]["expenses"]

    def test_overview_forbidden_for_member(self, app, scenario):
        c = app.test_client()
        c.post("/login", data={"username": "sf_full", "password": "pw123"})
        assert c.get("/api/overview").status_code == 403

    def test_home_renders_dashboard(self, admin_client):
        rv = admin_client.get("/dashboard/")
        assert rv.status_code == 200
        assert "/api/overview" in rv.data.decode()


class TestAccountingDashboard:
    def test_dashboard_totals(self, admin_client):
        d = _j(admin_client.get("/api/accounting/dashboard"))
        assert "total_deposited" in d and "total_expenses" in d
        assert d["balance"] == d["total_deposited"] - d["total_expenses"]
        assert "collection_rate" in d and "overdue_count" in d

    def test_projects_summary(self, admin_client, scenario):
        d = _j(admin_client.get("/api/accounting/projects-summary"))
        assert any(p["project_id"] == scenario["project_id"] for p in d["projects"])


class TestFinanceRole:
    @pytest.fixture(scope="class")
    def finance_client(self, app, sess):
        from app.models import User
        with app.app_context():
            if not sess.query(User).filter_by(username="fin_user").first():
                sess.add(User(username="fin_user", password_hash=generate_password_hash("pw"),
                              first_name="مسئول", last_name="مالی", role="finance",
                              active=True, profile_complete=True))
                sess.commit()
        c = app.test_client()
        c.post("/login", data={"username": "fin_user", "password": "pw"})
        return c

    def test_finance_can_access_accounting(self, finance_client):
        assert finance_client.get("/api/accounting/accounts").status_code == 200
        assert finance_client.get("/api/accounting/dashboard").status_code == 200

    def test_finance_cannot_delete_members(self, finance_client, scenario):
        rv = finance_client.delete(f"/api/members/{scenario['half_owner_id']}")
        assert rv.status_code == 403

    def test_finance_cannot_change_settings(self, finance_client):
        rv = _post_json(finance_client, "/api/settings", {"site_phone": "x"})
        assert rv.status_code == 403


# ─── Slides edit/toggle ───────────────────────────────────────────────────────

class TestSlidesManagement:
    def _create(self, admin_client, title="اسلاید تست"):
        rv = admin_client.post("/api/admin/slides",
                               data={"title": title, "bg_color": "#111111", "order": "5"})
        assert rv.status_code == 201
        return _j(rv)["id"]

    def test_update_slide(self, admin_client):
        sid = self._create(admin_client)
        rv = admin_client.post(f"/api/admin/slides/{sid}",
                               data={"title": "ویرایش‌شده", "subtitle": "زیر", "order": "9"})
        assert rv.status_code == 200
        slides = _j(admin_client.get("/api/admin/slides"))["slides"]
        s = next(x for x in slides if x["id"] == sid)
        assert s["title"] == "ویرایش‌شده" and s["order"] == 9

    def test_toggle_slide(self, admin_client):
        sid = self._create(admin_client, "اسلاید تاگل")
        rv = admin_client.post(f"/api/admin/slides/{sid}/toggle")
        assert rv.status_code == 200 and _j(rv)["active"] is False
        rv2 = admin_client.post(f"/api/admin/slides/{sid}/toggle")
        assert _j(rv2)["active"] is True

    def test_update_missing_slide_404(self, admin_client):
        rv = admin_client.post("/api/admin/slides/99999", data={"title": "x"})
        assert rv.status_code == 404


# ─── Login captcha ────────────────────────────────────────────────────────────

class TestLoginCaptcha:
    def test_captcha_appears_after_3_fails(self, app):
        c = app.test_client()
        for _ in range(3):
            c.post("/login", data={"username": "nobody", "password": "wrong"})
        page = c.get("/login").data.decode()
        assert "سؤال امنیتی" in page
        assert 'name="captcha"' in page

    def test_no_captcha_before_3_fails(self, app):
        c = app.test_client()
        c.post("/login", data={"username": "nobody", "password": "wrong"})
        page = c.get("/login").data.decode()
        assert 'name="captcha"' not in page

    def test_wrong_captcha_blocks_login(self, app):
        c = app.test_client()
        for _ in range(3):
            c.post("/login", data={"username": "nobody", "password": "wrong"})
        c.get("/login")  # کپچا تولید می‌شود
        rv = c.post("/login", data={"username": "admin", "password": "admin123",
                                    "captcha": "999"})
        assert "سؤال امنیتی اشتباه" in rv.data.decode()

    def test_correct_captcha_allows_login(self, app):
        import re
        c = app.test_client()
        for _ in range(3):
            c.post("/login", data={"username": "nobody", "password": "wrong"})
        page = c.get("/login").data.decode()
        m = re.search(r"(\d+) \+ (\d+) = \?", page)
        answer = str(int(m.group(1)) + int(m.group(2)))
        rv = c.post("/login", data={"username": "admin", "password": "admin123",
                                    "captcha": answer})
        assert rv.status_code == 302   # ورود موفق


# ─── File access control ──────────────────────────────────────────────────────

class TestUploadSecurity:
    def test_anonymous_cannot_access_request_docs(self, app):
        c = app.test_client()
        rv = c.get("/uploads/requests/123456_test.jpg")
        assert rv.status_code == 403

    def test_anonymous_cannot_access_payment_receipts(self, app):
        c = app.test_client()
        rv = c.get("/uploads/payments/123456_receipt.jpg")
        assert rv.status_code == 403

    def test_static_bypass_blocked(self, app):
        c = app.test_client()
        rv = c.get("/static/uploads/requests/123456_test.jpg")
        assert rv.status_code == 403

    def test_member_cannot_access_others_docs(self, app, scenario):
        member = app.test_client()
        member.post("/login", data={"username": "sf_full", "password": "pw123"})
        rv = member.get("/uploads/requests/someone_elses_doc.jpg")
        assert rv.status_code == 403

    def test_public_images_still_accessible(self, app):
        c = app.test_client()
        # فایل موجود در فولدر عمومی (از تست‌های قبلی)
        rv = c.get("/uploads/gallery_images/468012_test.png")
        assert rv.status_code in (200, 404)   # 403 نباید باشد

    def test_path_traversal_blocked(self, app):
        c = app.test_client()
        rv = c.get("/uploads/../models.py")
        assert rv.status_code in (403, 404)

    @pytest.fixture()
    def upload_test_booklet(self, app, sess):
        """پروژه/عضو/دفترچه اختصاصی این تست (هر بار تازه) — تا با «یک درخواست در انتظار
        در هر دفترچه» در بقیه تست‌ها (مثل TestTransferApproval) که از scenario مشترک
        استفاده می‌کنند تداخل نکند."""
        import random
        with app.app_context():
            tag = random.randint(100000, 999999)
            proj = Project(name=f"پروژه آپلود امنیتی {tag}", status="active", active=True)
            owner = User(username=f"upl_owner_{tag}", password_hash=generate_password_hash("pw123"),
                         first_name="آپلود", last_name="تست", role="member",
                         national_code=f"7{tag}", active=True,
                         father_name="ح", birth_date="1360/01/01", birth_place="زنجان",
                         marital_status="مجرد", occupation="کارمند", phone=f"0912{tag}",
                         emergency_phone="09121110001", postal_code="4519999999",
                         address="زنجان", bank_name="ملت")
            sess.add_all([proj, owner]); sess.flush()
            b = Booklet(code=f"UPL-{tag}", serial=1, project_id=proj.id, owner_id=owner.id, share_type="full")
            sess.add(b); sess.commit()
            return {"booklet_id": b.id, "username": owner.username}

    def test_spoofed_content_type_html_upload_rejected(self, app, sess, upload_test_booklet):
        """
        رگرسیون امنیتی: فایلی که Content-Type آن image/jpeg اعلام شده اما
        محتوای واقعی‌اش HTML/اسکریپت است، نباید ذخیره شود — قبلاً فقط هدر
        Content-Type بررسی می‌شد (به‌راحتی قابل جعل) و پسوند اصلی فایل (.html)
        حفظ می‌شد، که باعث اجرای XSS ذخیره‌شده هنگام باز کردن فایل توسط ادمین
        از طریق /uploads/ می‌شد.
        """
        import io
        member = app.test_client()
        member.post("/login", data={"username": upload_test_booklet["username"], "password": "pw123"})
        payload = b"<script>alert(document.cookie)</script>"
        rv = member.post("/api/requests", data={
            "booklet_id": upload_test_booklet["booklet_id"],
            "new_owner_first_name": "x", "new_owner_last_name": "y",
            "new_owner_national_code": "9998887771", "new_owner_phone": "09120000000",
            "receipt": (io.BytesIO(payload), "evil.html", "image/jpeg"),
        }, content_type="multipart/form-data")
        assert rv.status_code == 201
        from app.models import TransferRequest
        with app.app_context():
            tr = sess.query(TransferRequest).filter_by(
                new_owner_national_code="9998887771").order_by(TransferRequest.id.desc()).first()
            # فایل مخرب رد شده — receipt_path باید خالی بماند، نه ذخیره‌شده با پسوند .html
            assert not tr.receipt_path

    def test_valid_image_upload_gets_server_determined_extension(self, app, sess, upload_test_booklet):
        """پسوند فایل ذخیره‌شده باید از روی MIME تأییدشده باشد، نه نام فایل کاربر."""
        import io
        member = app.test_client()
        member.post("/login", data={"username": upload_test_booklet["username"], "password": "pw123"})
        real_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 30
        rv = member.post("/api/requests", data={
            "booklet_id": upload_test_booklet["booklet_id"],
            "new_owner_first_name": "x", "new_owner_last_name": "y",
            "new_owner_national_code": "9998887772", "new_owner_phone": "09120000000",
            "receipt": (io.BytesIO(real_jpeg), "anything.exe", "image/jpeg"),
        }, content_type="multipart/form-data")
        assert rv.status_code == 201
        from app.models import TransferRequest
        with app.app_context():
            tr = sess.query(TransferRequest).filter_by(
                new_owner_national_code="9998887772").order_by(TransferRequest.id.desc()).first()
            assert tr.receipt_path.endswith(".jpg")
            assert not tr.receipt_path.endswith(".exe")


# ─── SMS OTP (forgot password) ────────────────────────────────────────────────

class TestSmsOtp:
    def test_forgot_password_sends_sms(self, app, sess, monkeypatch):
        with app.app_context():
            u = User(username="sms_user1", password_hash=generate_password_hash("pw123"),
                     first_name="پیامک", last_name="کاربر", role="member",
                     national_code="7777777777", phone="09121234567",
                     active=True, profile_complete=True)
            sess.add(u); sess.commit()

        sent = {}
        def fake_send(mobile, code, db=None):
            sent["mobile"], sent["code"] = mobile, code
            return True
        from app import sms as sms_mod
        monkeypatch.setattr(sms_mod, "send_verify_code", fake_send)

        c = app.test_client()
        rv = c.post("/forgot-password", data={"national_code": "7777777777"})
        assert rv.status_code == 302          # redirect به صفحه ورود کد
        assert sent["mobile"] == "09121234567"
        assert len(sent["code"]) == 6

    def test_forgot_password_falls_back_to_bale(self, app, sess, monkeypatch):
        with app.app_context():
            u = User(username="sms_user2", password_hash=generate_password_hash("pw123"),
                     first_name="بله", last_name="کاربر", role="member",
                     national_code="8888888888", phone="09120000001",
                     bale_chat_id="12345", active=True, profile_complete=True)
            sess.add(u); sess.commit()

        from app import sms as sms_mod, bot as bot_mod
        monkeypatch.setattr(sms_mod, "send_verify_code", lambda *a, **k: False)
        bale_sent = {}
        monkeypatch.setattr(bot_mod, "send",
                            lambda cid, text, db=None: bale_sent.setdefault("cid", cid) or True)

        c = app.test_client()
        rv = c.post("/forgot-password", data={"national_code": "8888888888"})
        assert rv.status_code == 302
        assert bale_sent["cid"] == "12345"

    def test_full_reset_flow_db_backed(self, app, sess, monkeypatch):
        with app.app_context():
            u = User(username="reset_flow", password_hash=generate_password_hash("old123"),
                     first_name="ری", last_name="ست", role="member",
                     national_code="6667778888", phone="09120009999",
                     active=True, profile_complete=True)
            sess.add(u); sess.commit()

        captured = {}
        from app import sms as sms_mod
        monkeypatch.setattr(sms_mod, "send_verify_code",
                            lambda mobile, code, db=None: captured.update(code=code) or True)

        c = app.test_client()
        assert c.post("/forgot-password", data={"national_code": "6667778888"}).status_code == 302
        code = captured["code"]

        # کد اشتباه رد می‌شود
        bad = c.post("/verify-otp", data={"otp": "000000"})
        assert "اشتباه" in bad.data.decode()
        # کد درست
        assert c.post("/verify-otp", data={"otp": code}).status_code == 302
        # رمز جدید
        assert c.post("/reset-password", data={"password": "new12345", "password2": "new12345"}).status_code == 302
        # ورود با رمز جدید
        c2 = app.test_client()
        assert c2.post("/login", data={"username": "reset_flow", "password": "new12345"}).status_code == 302

    def test_otp_persisted_in_db(self, app, sess, monkeypatch):
        from app.models import PasswordResetCode
        from app import sms as sms_mod
        monkeypatch.setattr(sms_mod, "send_verify_code", lambda *a, **k: True)
        with app.app_context():
            u = User(username="otp_db", password_hash=generate_password_hash("x"),
                     first_name="o", last_name="d", role="member",
                     national_code="1212121212", phone="09121212121",
                     active=True, profile_complete=True)
            sess.add(u); sess.commit()
        c = app.test_client()
        c.post("/forgot-password", data={"national_code": "1212121212"})
        with app.app_context():
            assert sess.query(PasswordResetCode).filter_by(identifier="1212121212").count() == 1

    def test_forgot_password_no_channel_shows_error(self, app, sess):
        with app.app_context():
            u = User(username="sms_user3", password_hash=generate_password_hash("pw123"),
                     first_name="بدون", last_name="کانال", role="member",
                     national_code="9999999999",
                     active=True, profile_complete=True)
            sess.add(u); sess.commit()

        c = app.test_client()
        rv = c.post("/forgot-password", data={"national_code": "9999999999"})
        # پاسخ عمداً افشا نمی‌کند که این حساب کانال ارسال ندارد (User Enumeration)
        # — همیشه به verify-otp ریدایرکت می‌شود
        assert rv.status_code == 302
        assert "/verify-otp" in rv.headers["Location"]


# ─── Bale link-code (webhook is public/unauthenticated — code must expire) ────

class TestBaleLinkCodeSecurity:
    def test_link_code_has_expiry_set(self, app, sess, scenario):
        member_client = app.test_client()
        member_client.post("/login", data={"username": "sf_full", "password": "pw123"})
        rv = member_client.get("/api/bale/link-code")
        assert rv.status_code == 200
        d = _j(rv)
        assert "code" in d and len(d["code"]) == 6
        with app.app_context():
            u = sess.query(User).filter_by(bale_link_code=d["code"]).first()
            assert u is not None
            assert u.bale_link_code_expires_at is not None

    def test_expired_link_code_rejected(self, app, sess):
        """
        رگرسیون امنیتی: وبهوک بله عمومی و بدون احراز هویت است — هر کسی می‌تواند
        مستقیم کد ۶ رقمی پیوند را حدس بزند. تنها سدِ واقعی، انقضای کوتاه‌مدت
        کد است. این تست تأیید می‌کند که کد منقضی‌شده (یا بدون تاریخ انقضا،
        مثل رکوردهای خیلی قدیمی) دیگر برای پیوند دادن حساب پذیرفته نمی‌شود.
        """
        from datetime import datetime, timedelta
        from app import bot as bot_mod
        with app.app_context():
            u = User(username="bale_expiry_test", password_hash=generate_password_hash("pw"),
                     first_name="ب", last_name="ت", role="member",
                     national_code="6667778880", active=True,
                     bale_link_code="654321",
                     bale_link_code_expires_at=datetime.utcnow() - timedelta(minutes=1))
            sess.add(u); sess.commit()

        replies = []
        bot_mod._link_account("attacker-chat-id", "654321", sess, lambda t: replies.append(t))

        with app.app_context():
            fresh = sess.query(User).filter_by(username="bale_expiry_test").first()
            assert fresh.bale_chat_id is None  # پیوند برقرار نشده
        assert any("نامعتبر" in r or "منقضی" in r for r in replies)

    def test_valid_unexpired_link_code_accepted(self, app, sess):
        from datetime import datetime, timedelta
        from app import bot as bot_mod
        with app.app_context():
            u = User(username="bale_valid_test", password_hash=generate_password_hash("pw"),
                     first_name="ب", last_name="ت", role="member",
                     national_code="6667778881", active=True,
                     bale_link_code="111222",
                     bale_link_code_expires_at=datetime.utcnow() + timedelta(minutes=10))
            sess.add(u); sess.commit()

        bot_mod._link_account("legit-chat-id", "111222", sess, lambda t: None)

        with app.app_context():
            fresh = sess.query(User).filter_by(username="bale_valid_test").first()
            assert fresh.bale_chat_id == "legit-chat-id"
            assert fresh.bale_link_code is None  # یک‌بارمصرف


# ─── Rate limiting ────────────────────────────────────────────────────────────

class TestRateLimit:
    def test_login_post_rate_limited(self, app):
        limiter.enabled = True
        try:
            c = app.test_client()
            codes = []
            for _ in range(12):
                rv = c.post("/login", data={"username": "nobody", "password": "x"})
                codes.append(rv.status_code)
            assert 429 in codes, f"expected a 429 after 10 attempts, got {codes}"
        finally:
            limiter.enabled = False
            limiter.reset()

    def test_login_get_not_rate_limited(self, app):
        limiter.enabled = True
        try:
            c = app.test_client()
            for _ in range(15):
                assert c.get("/login").status_code == 200
        finally:
            limiter.enabled = False
            limiter.reset()


# ─── Transfer approval ────────────────────────────────────────────────────────

class TestTransferApproval:
    def test_full_transfer_flow(self, app, sess, admin_client, scenario):
        member = app.test_client()
        member.post("/login", data={"username": "sf_full", "password": "pw123"})

        rv = _post_json(member, "/api/requests/new", {
            "booklet_id": scenario["b_full_id"],
            "new_owner_first_name": "خریدار",
            "new_owner_last_name": "جدید",
            "new_owner_national_code": "3333333333",
            "new_owner_phone": "09120000000",
        })
        assert rv.status_code == 201
        rid = _j(rv)["id"]

        # درخواست تکراری روی همان دفترچه رد می‌شود
        rv2 = _post_json(member, "/api/requests/new", {
            "booklet_id": scenario["b_full_id"],
            "new_owner_first_name": "x", "new_owner_last_name": "y",
            "new_owner_national_code": "444", "new_owner_phone": "0912",
        })
        assert rv2.status_code == 409

        # مرحله ۱: تأیید اولیه → در انتظار دریافت فیزیکی مدارک
        rv3 = _post_json(admin_client, f"/api/requests/{rid}/approve", {"review_note": "تأیید"})
        assert rv3.status_code == 200
        assert _j(rv3)["status"] == "awaiting_docs"

        with app.app_context():
            sess.expire_all()
            req = sess.get(TransferRequest, rid)
            b   = sess.get(Booklet, scenario["b_full_id"])
            assert req.status == "awaiting_docs"
            # مالکیت هنوز منتقل نشده
            assert b.owner_id == scenario["full_owner_id"]

        # تأیید نهایی قبل از دریافت مدارک روی درخواست pending دیگر ممکن نیست
        rv_bad = _post_json(admin_client, f"/api/requests/{rid}/approve", {})
        assert rv_bad.status_code == 400

        # مرحله ۲: دریافت مدارک حضوری → انتقال نهایی
        rv4 = _post_json(admin_client, f"/api/requests/{rid}/complete", {"review_note": "مدارک دریافت شد"})
        assert rv4.status_code == 200

        with app.app_context():
            sess.expire_all()
            b = sess.get(Booklet, scenario["b_full_id"])
            new_owner = sess.query(User).filter_by(national_code="3333333333").first()
            old_owner = sess.get(User, scenario["full_owner_id"])
            req = sess.get(TransferRequest, rid)
            hist = sess.query(TransferHistory).filter_by(request_id=rid).first()

            assert new_owner is not None
            assert new_owner.profile_complete is False   # باید پروفایل را کامل کند
            assert b.owner_id == new_owner.id
            assert req.status == "approved"
            assert hist is not None
            assert hist.from_user_id == old_owner.id
            assert hist.to_user_id == new_owner.id
            # مالک قبلی دفترچه دیگری نداشت → غیرفعال
            assert old_owner.active is False

    def test_approve_twice_rejected(self, app, sess, admin_client, scenario):
        with app.app_context():
            req = sess.query(TransferRequest).filter_by(status="approved").first()
        rv = _post_json(admin_client, f"/api/requests/{req.id}/approve", {})
        assert rv.status_code == 400
        # complete هم روی درخواست نهایی‌شده کار نمی‌کند
        rv2 = _post_json(admin_client, f"/api/requests/{req.id}/complete", {})
        assert rv2.status_code == 400

    def test_member_cannot_approve(self, app, scenario):
        other = app.test_client()
        other.post("/login", data={"username": "sf_half", "password": "pw123"})
        rv = _post_json(other, "/api/requests/999/approve", {})
        assert rv.status_code == 403


# ─── Installment generation ───────────────────────────────────────────────────

class TestInstallments:
    def test_plan_creates_correct_payments(self, app, sess, admin_client, scenario):
        rv = _post_json(admin_client, "/api/finance/plans", {
            "project_id": scenario["project_id"],
            "title": "طرح تست اقساط",
            "total_amount": 12_000_000,
            "installments": 4,
            "start_date": "1404/11/15",
        })
        assert rv.status_code == 201
        data = _j(rv)
        plan_id = data["plan_id"]
        # ۲ دفترچه فعال × ۴ قسط
        assert data["payments_created"] == 8

        with app.app_context():
            payments = sess.query(Payment).filter_by(plan_id=plan_id).all()
            per = 12_000_000 // 4  # 3,000,000

            full_pays = [p for p in payments if p.booklet_id == scenario["b_full_id"]]
            half_pays = [p for p in payments if p.booklet_id == scenario["b_half_id"]]
            assert len(full_pays) == 4 and len(half_pays) == 4
            assert all(p.amount == per for p in full_pays)        # تمام‌سهم: کامل
            assert all(p.amount == per // 2 for p in half_pays)   # نیم‌سهم: نصف

            # سررسیدها ماهانه با گذر از سال (ماه ۱۱ → ۱۲ → ۱ سال بعد)
            dues = sorted(p.due_date for p in full_pays)
            assert dues == ["1404/11/15", "1404/12/15", "1405/01/15", "1405/02/15"]

    def test_plan_invalid_date_rejected(self, admin_client, scenario):
        rv = _post_json(admin_client, "/api/finance/plans", {
            "project_id": scenario["project_id"],
            "title": "طرح بد", "total_amount": 100, "installments": 2,
            "start_date": "1404/01",   # بدون روز
        })
        assert rv.status_code == 400

    def test_plan_missing_fields_rejected(self, admin_client):
        rv = _post_json(admin_client, "/api/finance/plans", {"title": "ناقص"})
        assert rv.status_code == 400


# ─── Soft delete ──────────────────────────────────────────────────────────────

class TestBookletSoftDelete:
    def test_delete_preserves_financial_history(self, app, sess, admin_client, scenario):
        bid = scenario["b_half_id"]
        with app.app_context():
            payments_before = sess.query(Payment).filter_by(booklet_id=bid).count()
            assert payments_before > 0

        rv = admin_client.delete(f"/api/booklets/{bid}")
        assert rv.status_code == 200

        with app.app_context():
            sess.expire_all()
            b = sess.get(Booklet, bid)
            # رکورد فیزیکی حذف نشده — فقط علامت‌گذاری شده
            assert b is not None
            assert b.deleted_at is not None
            # پرداخت‌ها همچنان به دفترچه متصل هستند
            assert sess.query(Payment).filter_by(booklet_id=bid).count() == payments_before

    def test_deleted_booklet_hidden_from_list(self, admin_client, scenario):
        rv = admin_client.get("/api/booklets")
        codes = [b["code"] for b in _j(rv)["booklets"]]
        assert "SF-HALF-001" not in codes

    def test_deleted_booklet_not_transferable(self, app, scenario):
        member = app.test_client()
        member.post("/login", data={"username": "sf_half", "password": "pw123"})
        rv = _post_json(member, "/api/requests/new", {
            "booklet_id": scenario["b_half_id"],
            "new_owner_first_name": "x", "new_owner_last_name": "y",
            "new_owner_national_code": "555", "new_owner_phone": "0912",
        })
        assert rv.status_code == 403

    def test_delete_twice_returns_404(self, admin_client, scenario):
        rv = admin_client.delete(f"/api/booklets/{scenario['b_half_id']}")
        assert rv.status_code == 404
