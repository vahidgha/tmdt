"""
تست‌های ماژول بازار خرید و فروش دفترچه‌ها (Marketplace).
سناریوهای اصلی: ثبت آگهی، جریان پرداخت/بررسی، Snapshot هزینه، IDOR،
دسترسی مهمان، اتصال به Ticketing، وضعیت‌های Sold/Expired، SEO.
"""
import io
import json
from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app.models import (
    Booklet, MarketplaceListing, MarketplacePurchaseRequest, Project,
    SiteSetting, Ticket, User,
)


def _j(rv):
    return json.loads(rv.data)


def _post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


@pytest.fixture(scope="module")
def sess(app):
    return app.db


@pytest.fixture(scope="module")
def admin_client(app):
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin123"})
    return c


@pytest.fixture(scope="module")
def scenario(app, sess):
    """پروژه + دو عضو فروشنده هرکدام با یک دفترچه."""
    with app.app_context():
        proj = Project(name="پروژه بازار تست", status="active", active=True)
        sess.add(proj); sess.flush()

        req_kwargs = dict(
            father_name="حسن", birth_date="1360/01/01", birth_place="زنجان",
            marital_status="متأهل", occupation="کارمند",
            postal_code="4519999999", address="زنجان", bank_name="ملت",
        )
        seller1 = User(username="mkt_seller1", password_hash=generate_password_hash("pw123"),
                        first_name="فروشنده", last_name="یک", role="member",
                        national_code="3001001001", phone="09131110001",
                        emergency_phone="09131110002", active=True, **req_kwargs)
        seller2 = User(username="mkt_seller2", password_hash=generate_password_hash("pw123"),
                        first_name="فروشنده", last_name="دو", role="member",
                        national_code="3001001002", phone="09131110003",
                        emergency_phone="09131110004", active=True, **req_kwargs)
        sess.add_all([seller1, seller2]); sess.flush()

        b1 = Booklet(code="MKT-B1", serial=1, project_id=proj.id, owner_id=seller1.id, share_type="full")
        b2 = Booklet(code="MKT-B2", serial=2, project_id=proj.id, owner_id=seller2.id, share_type="half")
        sess.add_all([b1, b2]); sess.commit()

        return {
            "project_id": proj.id,
            "seller1_id": seller1.id, "seller2_id": seller2.id,
            "b1_id": b1.id, "b2_id": b2.id,
        }


@pytest.fixture()
def seller1_client(app, scenario):
    c = app.test_client()
    c.post("/login", data={"username": "mkt_seller1", "password": "pw123"})
    return c


@pytest.fixture()
def seller2_client(app, scenario):
    c = app.test_client()
    c.post("/login", data={"username": "mkt_seller2", "password": "pw123"})
    return c


def _set_fee(app, sess, amount, enabled=True):
    with app.app_context():
        for k, v in (("marketplace_fee_amount", str(amount)),
                     ("marketplace_fee_enabled", "1" if enabled else "0")):
            row = sess.query(SiteSetting).filter_by(key=k).first()
            if row: row.value = v
            else: sess.add(SiteSetting(key=k, value=v))
        sess.commit()


def _create_listing(client, booklet_id, **overrides):
    data = {
        "booklet_id": booklet_id, "title": "دفترچه تست بازار",
        "price": "500000000", "contact_method": "request",
    }
    data.update(overrides)
    return _post_json(client, "/api/marketplace/listings", data)


class TestListingCreation:
    def test_guest_cannot_create_listing(self, app, scenario):
        c = app.test_client()
        rv = _create_listing(c, scenario["b1_id"])
        assert rv.status_code in (302, 401)  # login_required redirects/401s

    def test_member_can_create_listing(self, app, sess, scenario, seller1_client):
        _set_fee(app, sess, 260000, True)
        rv = _create_listing(seller1_client, scenario["b1_id"])
        assert rv.status_code == 201
        d = _j(rv)["listing"]
        assert d["status"] == "waiting_payment"
        assert d["fee_amount"] == 260000
        assert d["fee_required"] is True

    def test_member_cannot_list_someone_elses_booklet(self, app, scenario, seller1_client):
        rv = _create_listing(seller1_client, scenario["b2_id"])
        assert rv.status_code == 403

    def test_duplicate_active_listing_rejected(self, app, sess, scenario, seller1_client):
        _set_fee(app, sess, 260000, True)
        rv1 = _create_listing(seller1_client, scenario["b1_id"], title="دومین تلاش")
        # قبلاً یک آگهی فعال برای b1 در تست قبلی ساخته شده
        assert rv1.status_code == 409


class TestFeeSnapshot:
    def test_fee_is_snapshotted_and_survives_setting_change(self, app, sess, scenario, seller2_client):
        _set_fee(app, sess, 260000, True)
        rv = _create_listing(seller2_client, scenario["b2_id"], title="آگهی اسنپ‌شات")
        assert rv.status_code == 201
        listing_id = _j(rv)["listing"]["id"]
        assert _j(rv)["listing"]["fee_amount"] == 260000

        # مدیر مبلغ هزینه را تغییر می‌دهد
        _set_fee(app, sess, 350000, True)

        with app.app_context():
            lst = sess.get(MarketplaceListing, listing_id)
            assert lst.fee_amount == 260000  # دست‌نخورده باقی مانده

    def test_frontend_cannot_override_fee_amount(self, app, sess, scenario, seller1_client):
        """کاربر نباید بتواند مبلغ هزینه را از طریق بدنه درخواست دستکاری کند."""
        with app.app_context():
            # پاک‌سازی آگهی‌های فعال قبلی seller1 برای این تست مستقل
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller1_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 260000, True)
        rv = _create_listing(seller1_client, scenario["b1_id"], fee_amount="1")
        assert rv.status_code == 201
        assert _j(rv)["listing"]["fee_amount"] == 260000  # مقدار جعلی نادیده گرفته شد


class TestFreeMode:
    def test_zero_fee_skips_payment_stage(self, app, sess, scenario, seller2_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller2_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller2_client, scenario["b2_id"], title="آگهی رایگان")
        assert rv.status_code == 201
        d = _j(rv)["listing"]
        assert d["status"] == "admin_review"  # مستقیم به بررسی ادمین، بدون مرحله پرداخت
        assert d["fee_required"] is False


class TestPaymentAndReview:
    @pytest.fixture()
    def paid_listing(self, app, sess, scenario, seller1_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller1_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 260000, True)
        rv = _create_listing(seller1_client, scenario["b1_id"], title="آگهی جریان کامل")
        lid = _j(rv)["listing"]["id"]

        real_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 30
        rv2 = seller1_client.post(f"/api/marketplace/listings/{lid}/payment", data={
            "receipt": (io.BytesIO(real_jpeg), "receipt.jpg", "image/jpeg"),
            "payment_date": "1404/05/16",
        }, content_type="multipart/form-data")
        assert rv2.status_code == 200
        return lid

    def test_receipt_only_visible_to_owner_and_admin(self, app, sess, paid_listing, seller1_client, seller2_client):
        with app.app_context():
            path = sess.get(MarketplaceListing, paid_listing).payment_receipt_path
        assert path

        rv_owner = seller1_client.get(f"/uploads/{path}")
        assert rv_owner.status_code == 200

        rv_other = seller2_client.get(f"/uploads/{path}")
        assert rv_other.status_code == 403

        rv_anon = app.test_client().get(f"/uploads/{path}")
        assert rv_anon.status_code == 403

    def test_admin_can_approve_payment_then_listing(self, app, admin_client, paid_listing):
        rv1 = admin_client.post(f"/api/marketplace/admin/listings/{paid_listing}/approve-payment")
        assert rv1.status_code == 200
        with app.app_context():
            pass
        rv_detail = admin_client.get(f"/api/marketplace/admin/listings/{paid_listing}")
        assert _j(rv_detail)["listing"]["status"] == "admin_review"

        rv2 = admin_client.post(f"/api/marketplace/admin/listings/{paid_listing}/approve")
        assert rv2.status_code == 200
        rv_detail2 = admin_client.get(f"/api/marketplace/admin/listings/{paid_listing}")
        d = _j(rv_detail2)["listing"]
        assert d["status"] == "published"
        assert d["published_at"] is not None
        assert d["expires_at"] is not None

    def test_reject_requires_reason(self, app, admin_client, sess, scenario, seller2_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller2_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller2_client, scenario["b2_id"], title="آگهی برای رد")
        lid = _j(rv)["listing"]["id"]
        rv_bad = _post_json(admin_client, f"/api/marketplace/admin/listings/{lid}/reject", {})
        assert rv_bad.status_code == 400
        rv_ok = _post_json(admin_client, f"/api/marketplace/admin/listings/{lid}/reject", {"reason": "مدارک ناقص"})
        assert rv_ok.status_code == 200
        with app.app_context():
            lst = sess.get(MarketplaceListing, lid)
            assert lst.status == "rejected"
            assert lst.reject_reason == "مدارک ناقص"


class TestPublicMarketplace:
    @pytest.fixture()
    def published_listing(self, app, sess, admin_client, scenario, seller1_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller1_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller1_client, scenario["b1_id"], title="آگهی عمومی تست",
                              contact_method="both", contact_phone="09121234567")
        lid = _j(rv)["listing"]["id"]
        admin_client.post(f"/api/marketplace/admin/listings/{lid}/approve")
        with app.app_context():
            return sess.get(MarketplaceListing, lid).slug

    def test_unpublished_listing_not_public(self, app, sess, scenario, seller2_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller2_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller2_client, scenario["b2_id"], title="آگهی هنوز تأییدنشده")
        slug = _j(rv)["listing"]["slug"]
        c = app.test_client()
        rv_pub = c.get(f"/api/marketplace/listings/{slug}")
        assert rv_pub.status_code == 404
        rv_page = c.get(f"/marketplace/{slug}")
        assert rv_page.status_code == 404

    def test_published_listing_visible_publicly(self, app, published_listing):
        c = app.test_client()
        rv = c.get(f"/api/marketplace/listings/{published_listing}")
        assert rv.status_code == 200
        rv_page = c.get(f"/marketplace/{published_listing}")
        assert rv_page.status_code == 200

    def test_phone_hidden_when_not_allowed(self, app, sess, admin_client, scenario, seller2_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller2_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller2_client, scenario["b2_id"], title="آگهی بدون شماره",
                              contact_method="request")
        lid = _j(rv)["listing"]["id"]
        admin_client.post(f"/api/marketplace/admin/listings/{lid}/approve")
        with app.app_context():
            slug = sess.get(MarketplaceListing, lid).slug
        rv_pub = app.test_client().get(f"/api/marketplace/listings/{slug}")
        assert "contact_phone" not in _j(rv_pub)["listing"]

    def test_phone_shown_when_allowed(self, app, published_listing):
        rv = app.test_client().get(f"/api/marketplace/listings/{published_listing}")
        assert _j(rv)["listing"].get("contact_phone") == "09121234567"


class TestPurchaseRequestAndTicketing:
    @pytest.fixture()
    def published_listing_id(self, app, sess, admin_client, scenario, seller1_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller1_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller1_client, scenario["b1_id"], title="آگهی برای درخواست خرید")
        lid = _j(rv)["listing"]["id"]
        admin_client.post(f"/api/marketplace/admin/listings/{lid}/approve")
        return lid

    def test_guest_can_submit_purchase_request(self, app, published_listing_id):
        c = app.test_client()
        rv = c.post(f"/api/marketplace/listings/{published_listing_id}/purchase-request", json={
            "buyer_name": "خریدار مهمان", "buyer_phone": "09359998877", "message": "سلام، قیمت قابل تخفیف است؟",
        })
        assert rv.status_code == 201

    def test_purchase_request_creates_ticket(self, app, sess, published_listing_id):
        with app.app_context():
            pr = (sess.query(MarketplacePurchaseRequest)
                  .filter_by(listing_id=published_listing_id).order_by(
                      MarketplacePurchaseRequest.id.desc()).first())
            assert pr is not None
            assert pr.ticket_id is not None
            t = sess.get(Ticket, pr.ticket_id)
            assert t is not None
            assert t.listing_id == published_listing_id

    def test_seller_can_see_purchase_requests(self, app, seller1_client, published_listing_id):
        rv = seller1_client.get("/api/marketplace/my-requests")
        assert rv.status_code == 200
        items = _j(rv)["requests"]
        assert any(r["listing_id"] == published_listing_id for r in items)

    def test_other_member_cannot_see_ticket(self, app, sess, seller2_client, published_listing_id):
        with app.app_context():
            pr = (sess.query(MarketplacePurchaseRequest)
                  .filter_by(listing_id=published_listing_id).order_by(
                      MarketplacePurchaseRequest.id.desc()).first())
            tid = pr.ticket_id
        rv = seller2_client.get(f"/api/tickets/{tid}")
        assert rv.status_code == 403

    def test_seller_can_see_ticket(self, app, sess, seller1_client, published_listing_id):
        with app.app_context():
            pr = (sess.query(MarketplacePurchaseRequest)
                  .filter_by(listing_id=published_listing_id).order_by(
                      MarketplacePurchaseRequest.id.desc()).first())
            tid = pr.ticket_id
        rv = seller1_client.get(f"/api/tickets/{tid}")
        assert rv.status_code == 200

    def test_phone_only_listing_rejects_purchase_request(self, app, sess, admin_client, scenario, seller2_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller2_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller2_client, scenario["b2_id"], title="فقط تماس تلفنی",
                              contact_method="phone", contact_phone="09120000000")
        lid = _j(rv)["listing"]["id"]
        admin_client.post(f"/api/marketplace/admin/listings/{lid}/approve")
        c = app.test_client()
        rv_req = c.post(f"/api/marketplace/listings/{lid}/purchase-request", json={
            "buyer_name": "کسی", "buyer_phone": "09120000001",
        })
        assert rv_req.status_code == 400


class TestSoldAndExpired:
    def test_seller_can_mark_sold_and_it_leaves_marketplace(self, app, sess, admin_client, scenario, seller1_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller1_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller1_client, scenario["b1_id"], title="آگهی برای فروش")
        lid = _j(rv)["listing"]["id"]
        admin_client.post(f"/api/marketplace/admin/listings/{lid}/approve")
        with app.app_context():
            slug = sess.get(MarketplaceListing, lid).slug

        rv_sold = seller1_client.post(f"/api/marketplace/listings/{lid}/sold")
        assert rv_sold.status_code == 200

        rv_pub = app.test_client().get(f"/api/marketplace/listings/{slug}")
        assert rv_pub.status_code == 404

    def test_expired_listing_hidden_from_public(self, app, sess, admin_client, scenario, seller2_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller2_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller2_client, scenario["b2_id"], title="آگهی منقضی‌شونده")
        lid = _j(rv)["listing"]["id"]
        admin_client.post(f"/api/marketplace/admin/listings/{lid}/approve")
        with app.app_context():
            lst = sess.get(MarketplaceListing, lid)
            lst.expires_at = datetime.utcnow() - timedelta(days=1)
            sess.commit()
            slug = lst.slug

        rv_pub = app.test_client().get(f"/api/marketplace/listings/{slug}")
        assert rv_pub.status_code == 404


class TestSecurity:
    def test_member_cannot_edit_other_members_listing(self, app, sess, scenario, seller1_client, seller2_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller1_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller1_client, scenario["b1_id"], title="آگهی محرمانه فروشنده یک")
        lid = _j(rv)["listing"]["id"]

        rv_hack = _post_json(seller2_client, f"/api/marketplace/listings/{lid}", {"price": "1"})
        assert rv_hack.status_code == 404  # عدم افشای وجود منبع برای کاربر غیرمجاز

        with app.app_context():
            lst = sess.get(MarketplaceListing, lid)
            assert lst.price != 1  # قیمت واقعاً تغییر نکرده

    def test_admin_endpoints_blocked_for_member(self, app, seller1_client):
        rv = seller1_client.get("/api/marketplace/admin/listings")
        assert rv.status_code == 403
        rv2 = seller1_client.get("/api/marketplace/admin/stats")
        assert rv2.status_code == 403

    def test_spoofed_receipt_upload_rejected(self, app, sess, scenario, seller1_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller1_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 260000, True)
        rv = _create_listing(seller1_client, scenario["b1_id"], title="آگهی برای تست آپلود")
        lid = _j(rv)["listing"]["id"]

        payload = b"<script>alert(1)</script>"
        rv2 = seller1_client.post(f"/api/marketplace/listings/{lid}/payment", data={
            "receipt": (io.BytesIO(payload), "evil.html", "image/jpeg"),
            "payment_date": "1404/05/16",
        }, content_type="multipart/form-data")
        assert rv2.status_code == 400
        with app.app_context():
            lst = sess.get(MarketplaceListing, lid)
            assert lst.status == "waiting_payment"  # هنوز منتظر پرداخت معتبر است
            assert not lst.payment_receipt_path


class TestSEO:
    def test_published_listing_appears_in_sitemap(self, app, sess, admin_client, scenario, seller1_client):
        with app.app_context():
            sess.query(MarketplaceListing).filter_by(seller_id=scenario["seller1_id"]).delete()
            sess.commit()
        _set_fee(app, sess, 0, True)
        rv = _create_listing(seller1_client, scenario["b1_id"], title="آگهی برای سایت‌مپ")
        lid = _j(rv)["listing"]["id"]
        admin_client.post(f"/api/marketplace/admin/listings/{lid}/approve")
        with app.app_context():
            slug = sess.get(MarketplaceListing, lid).slug

        rv_sitemap = app.test_client().get("/sitemap.xml")
        assert f"/marketplace/{slug}" in rv_sitemap.data.decode()
