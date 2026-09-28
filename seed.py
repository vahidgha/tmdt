#!/usr/bin/env python3
"""
seed.py — داده‌های نمونه برای تست سامانه هیئت امنای مسکن دادگستری زنجان
اجرا: python seed.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app, db_session
from app.models import (User, Booklet, Project, ProjectMember,
                        Announcement, PaymentPlan, Payment, Notification,
                        Slide, SiteSetting, TransferRequest)
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random, math

app = create_app()

with app.app_context():
    print("\n🌱 شروع بارگذاری داده‌های نمونه...")

    # ─── تنظیمات سایت ──────────────────────────────────────────────────────
    settings = {
        "site_title":    "هیئت امنای مسکن دادگستری زنجان",
        "site_subtitle": "سامانه آنلاین مدیریت دفترچه مالکیت",
        "site_phone":    "024-33445566",
        "site_address":  "زنجان، خیابان دادگستری، ساختمان هیئت امنا",
        "hero_btn_label":"ورود اعضا",
        "exec_manager":  "علی غفاری",
        "board_rep":     "خلیل باقری",
        "board_title":   "هیئت رئیسه امنای مسکن دادگستری استان زنجان",
    }
    for k, v in settings.items():
        row = db_session.get(SiteSetting, k)
        if row: row.value = v
        else: db_session.add(SiteSetting(key=k, value=v))
    print("  ✅ تنظیمات سایت")

    # ─── پروژه‌ها ───────────────────────────────────────────────────────────
    projects_data = [
        {
            "name": "مجتمع مسکونی بهارستان",
            "address": "زنجان، بلوار آزادی، کوچه بهار ۳",
            "location": "شهرک بهارستان",
            "total_booklets": 48,
            "start_date": "1402/03/01",
            "end_date": "1406/06/01",
            "status": "active",
            "order": 1,
            "members": [
                {"role": "مدیر اجرایی",      "full_name": "علی غفاری",       "phone": "09121234567", "order": 1},
                {"role": "رئیس هیئت اجرایی", "full_name": "خلیل باقری",      "phone": "09129876543", "order": 2},
                {"role": "مدیر هیئت امنا",   "full_name": "محمد رضایی",      "phone": "09135554321", "order": 3},
                {"role": "مدیر هیئت امنا",   "full_name": "حسین موسوی",      "phone": "09137778899", "order": 4},
            ]
        },
        {
            "name": "برج‌های گلستان",
            "address": "زنجان، خیابان امام خمینی، پلاک ۱۴۵",
            "location": "مرکز شهر",
            "total_booklets": 80,
            "start_date": "1403/01/15",
            "end_date": "1408/01/15",
            "status": "active",
            "order": 2,
            "members": [
                {"role": "مدیر اجرایی",      "full_name": "علی غفاری",       "phone": "09121234567", "order": 1},
                {"role": "رئیس هیئت اجرایی", "full_name": "خلیل باقری",      "phone": "09129876543", "order": 2},
                {"role": "مدیر هیئت امنا",   "full_name": "رضا احمدی",       "phone": "09143332211", "order": 3},
                {"role": "مدیر هیئت امنا",   "full_name": "علیرضا کریمی",    "phone": "09151116677", "order": 4},
            ]
        },
        {
            "name": "ویلاهای سبز دادگستری",
            "address": "زنجان، جاده قدیم تبریز، کیلومتر ۸",
            "location": "حومه شهر",
            "total_booklets": 24,
            "start_date": "1405/06/01",
            "end_date": "1410/06/01",
            "status": "upcoming",
            "order": 3,
            "members": [
                {"role": "مدیر اجرایی",      "full_name": "علی غفاری",       "phone": "09121234567", "order": 1},
                {"role": "رئیس هیئت اجرایی", "full_name": "خلیل باقری",      "phone": "09129876543", "order": 2},
                {"role": "مدیر هیئت امنا",   "full_name": "سعید تهرانی",     "phone": "09162223344", "order": 3},
                {"role": "مدیر هیئت امنا",   "full_name": "جواد صادقی",      "phone": "09174445566", "order": 4},
            ]
        },
    ]

    projects = []
    for pd in projects_data:
        p = db_session.query(Project).filter_by(name=pd["name"]).first()
        if not p:
            mems = pd.pop("members", [])
            p = Project(**pd)
            db_session.add(p)
            db_session.flush()
            for md in mems:
                db_session.add(ProjectMember(project_id=p.id, **md))
        projects.append(p)
    db_session.flush()
    print(f"  ✅ {len(projects)} پروژه")

    # ─── اعضا و دفترچه‌ها ──────────────────────────────────────────────────
    members_data = [
        # (نام, نام‌خانوادگی, کد ملی, موبایل, پروژه‌ایندکس, نوع‌سهم)
        ("احمد",    "محمدی",   "4230156789", "09121110001", 0, "full"),
        ("فاطمه",   "حسینی",   "4230156790", "09122220002", 0, "full"),
        ("محمود",   "رضایی",   "4230156791", "09133330003", 0, "half"),
        ("زهرا",    "کریمی",   "4230156792", "09144440004", 0, "full"),
        ("علیرضا",  "موسوی",   "4230156793", "09155550005", 1, "full"),
        ("مریم",    "احمدی",   "4230156794", "09166660006", 1, "half"),
        ("حسن",     "صادقی",   "4230156795", "09177770007", 1, "full"),
        ("نرگس",    "تهرانی",  "4230156796", "09188880008", 1, "full"),
        ("سعید",    "غفاری",   "4230156797", "09199990009", 2, "full"),
        ("لیلا",    "باقری",   "4230156798", "09101110010", 2, "half"),
    ]

    members = []
    codes_used = {b.code for b in db_session.query(Booklet).all()}

    for fn, ln, nat, phone, proj_idx, share in members_data:
        username = nat
        u = db_session.query(User).filter_by(username=username).first()
        if not u:
            u = User(
                username=username,
                password_hash=generate_password_hash("1234"),
                role="member",
                first_name=fn, last_name=ln,
                national_code=nat, phone=phone,
                father_name="حسین",
                birth_date="1360/05/12",
                birth_place="زنجان",
                marital_status="متأهل",
                occupation="کارمند دادگستری",
                address="زنجان، خیابان دادگستری",
                postal_code="4516893412",
                bank_name="ملی",
                account_number=f"01720{nat[-6:]}",
                active=True, profile_complete=True,
            )
            db_session.add(u); db_session.flush()

            # کد دفترچه یکتا
            while True:
                code = f"ZNJ-{proj_idx+1:03d}-{random.randint(100000,999999)}"
                if code not in codes_used:
                    codes_used.add(code); break

            proj = projects[proj_idx]
            b = Booklet(
                code=code, owner_id=u.id, project_id=proj.id,
                share_type=share,
                contract_no=f"Q-{1403}-{nat[-4:]}",
                contract_date="1403/01/01",
                contract_amount=1_800_000_000 if share=="full" else 900_000_000,
            )
            db_session.add(b)
        members.append(u)

    db_session.flush()
    print(f"  ✅ {len(members_data)} عضو و دفترچه")

    # ─── طرح پرداخت و اقساط ────────────────────────────────────────────────
    for proj_idx, proj in enumerate(projects[:2]):
        plan_title = f"شارژ سال ۱۴۰۳ — {proj.name}"
        if db_session.query(PaymentPlan).filter_by(title=plan_title).first():
            continue
        plan = PaymentPlan(
            project_id=proj.id,
            title=plan_title,
            total_amount=12_000_000,
            installments=12,
            start_date="1403/01/01",
            description="شارژ ماهیانه سال ۱۴۰۳",
        )
        db_session.add(plan); db_session.flush()

        booklets = db_session.query(Booklet).filter_by(project_id=proj.id).all()
        per = math.ceil(plan.total_amount / plan.installments)
        for b in booklets:
            amt = per if b.share_type == "full" else per // 2
            for i in range(12):
                m = 1 + i
                status = "paid" if i < 4 else ("overdue" if i == 4 else "unpaid")
                paid_date = f"1403/{str(m).zfill(2)}/05" if status == "paid" else None
                db_session.add(Payment(
                    user_id=b.owner_id, booklet_id=b.id, plan_id=plan.id,
                    amount=amt,
                    due_date=f"1403/{str(m).zfill(2)}/01",
                    paid_date=paid_date, status=status,
                    description=f"{plan.title} — قسط {i+1} از 12",
                ))

    db_session.flush()
    print("  ✅ طرح پرداخت و اقساط")

    # ─── اطلاعیه‌ها ─────────────────────────────────────────────────────────
    anns = [
        ("برگزاری مجمع عمومی سالیانه",
         "به اطلاع کلیه اعضای محترم می‌رساند جلسه مجمع عمومی سالیانه هیئت امنای مسکن دادگستری استان زنجان روز پنجشنبه مورخ ۱۴۰۳/۰۵/۱۱ ساعت ۱۷:۰۰ در محل سالن اجتماعات دادگستری برگزار می‌شود. حضور کلیه اعضا الزامی است."),
        ("پرداخت اقساط معوقه",
         "به اعضایی که دارای قسط معوقه می‌باشند اطلاع داده می‌شود حداکثر تا تاریخ ۱۴۰۳/۰۶/۳۱ نسبت به تسویه اقساط خود اقدام نمایند. در غیر این صورت طبق مفاد قرارداد اقدام لازم صورت خواهد گرفت."),
        ("شروع عملیات اجرایی پروژه بهارستان",
         "خوشحالیم اعلام کنیم که عملیات اجرایی پروژه مجتمع مسکونی بهارستان از تاریخ ۱۴۰۳/۰۴/۰۱ آغاز شده است. پیشرفت پروژه هر ماه از طریق همین سامانه اطلاع‌رسانی خواهد شد."),
        ("تغییر ساعت کار دفتر",
         "با احترام، ساعت کار دفتر هیئت امنا از شنبه تا چهارشنبه از ساعت ۸:۳۰ تا ۱۳:۳۰ و ۱۴:۳۰ تا ۱۷:۰۰ اعلام می‌گردد."),
    ]
    admin = db_session.query(User).filter_by(username="admin").first()
    from app.models import Announcement
    for title, body in anns:
        if not db_session.query(Announcement).filter_by(title=title).first():
            db_session.add(Announcement(
                title=title, body=body,
                author="مدیریت هیئت امنا",
                author_id=admin.id if admin else None,
            ))
    print("  ✅ ۴ اطلاعیه")

    # ─── اعلان‌ها ───────────────────────────────────────────────────────────
    for m in members:
        if db_session.query(Notification).filter_by(user_id=m.id).count() == 0:
            db_session.add(Notification(
                user_id=m.id, type="info",
                title="خوش آمدید به سامانه",
                body="حساب کاربری شما در سامانه هیئت امنای مسکن دادگستری زنجان فعال شد.",
            ))
            db_session.add(Notification(
                user_id=m.id, type="warning",
                title="یادآوری پرداخت قسط",
                body="قسط ماه مرداد شما هنوز پرداخت نشده است. لطفاً تا پایان ماه اقدام کنید.",
            ))
    print("  ✅ اعلان‌های اولیه")

    # ─── اسلایدهای صفحه عمومی ──────────────────────────────────────────────
    slides_data = [
        {"title": "هیئت امنای مسکن دادگستری زنجان",
         "subtitle": "خانه‌ای برای همه کارکنان خانواده دادگستری",
         "bg_color": "#1A2640", "order": 1},
        {"title": "پروژه‌های مسکونی با کیفیت",
         "subtitle": "واحدهای مسکونی مجهز در بهترین مناطق زنجان",
         "bg_color": "#0C2340", "order": 2},
        {"title": "سرمایه‌گذاری مطمئن",
         "subtitle": "با خرید دفترچه مالکیت از آینده‌ای مطمئن برخوردار شوید",
         "bg_color": "#1C1A2E", "order": 3},
    ]
    from app.models import Slide
    for sd in slides_data:
        if not db_session.query(Slide).filter_by(title=sd["title"]).first():
            db_session.add(Slide(**sd, active=True))
    print("  ✅ اسلایدهای صفحه عمومی")

    db_session.commit()
    print("""
╔══════════════════════════════════════════════════╗
║  ✅ داده‌های نمونه با موفقیت بارگذاری شدند!      ║
╠══════════════════════════════════════════════════╣
║  ورود مدیر:  admin / admin123                    ║
║  ورود اعضا:  [کد ملی] / 1234                    ║
║                                                  ║
║  اعضای نمونه:                                    ║
║  • احمد محمدی    → 4230156789 / 1234             ║
║  • فاطمه حسینی   → 4230156790 / 1234             ║
║  • محمود رضایی   → 4230156791 / 1234             ║
║  • علیرضا موسوی  → 4230156793 / 1234             ║
║  • حسن صادقی    → 4230156795 / 1234             ║
╚══════════════════════════════════════════════════╝
    """)
