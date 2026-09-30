"""مدل‌های ORM سامانه — تمام جدول‌های دیتابیس (SQLAlchemy 2 Declarative) در این فایل تعریف شده‌اند.

شامل: کاربران/اعضا، پروژه‌ها و دفترچه‌ها، درخواست‌ها و تاریخچه انتقال مالکیت،
اطلاعیه‌ها، طرح‌ها و اقساط پرداخت، اعلان‌ها، تنظیمات سایت، اسناد مالی (واریز/هزینه/دفتر معین)،
لاگ فعالیت، سیستم تیکتینگ، فرم‌ساز پویا و بازار خرید‌وفروش دفترچه.

قواعد کلی رعایت‌شده در این فایل:
- رکوردهای مالی (اسناد واریز/هزینه/دفتر معین) هرگز حذف فیزیکی نمی‌شوند؛ فقط
  «ابطال» می‌شوند (status=voided + void_reason) تا سابقه حسابرسی حفظ بماند.
- مالکیت دفترچه (Booklet) هم soft-delete است — رکورد قدیمی برای سابقه انتقال
  باقی می‌ماند اما در روابط فعال (User.booklets/Project.booklets) فیلتر می‌شود.
- متد to_dict() روی اغلب مدل‌ها برای سریالایز مستقیم به JSON در APIها استفاده می‌شود.
"""
from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Text, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """کلاس پایه Declarative برای همه مدل‌های ORM."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# User  (نام و نام خانوادگی جدا)
# ─────────────────────────────────────────────────────────────────────────────
class User(UserMixin, Base):
    """کاربر سامانه — هم عضو تعاونی (role=member) و هم مدیر (role=admin) از این مدل هستند."""
    __tablename__ = "users"

    id               = Column(Integer, primary_key=True)
    username         = Column(String(80),  unique=True, nullable=False)
    password_hash    = Column(String(256), nullable=False)
    role             = Column(String(20),  default="member")   # admin | member

    first_name       = Column(String(60),  nullable=False, default="")   # نام
    last_name        = Column(String(60),  nullable=False, default="")   # نام خانوادگی

    national_code    = Column(String(10))
    gender           = Column(String(10))    # مرد / زن
    id_number        = Column(String(20))    # شماره شناسنامه
    phone            = Column(String(15))
    emergency_phone  = Column(String(15))
    active           = Column(Boolean, default=True)
    profile_complete = Column(Boolean, default=True)

    personnel_code   = Column(String(20))               # کدپرسنلی
    deposit_id       = Column(String(30), unique=True)  # شناسه واریز — برای تطبیق خودکار واریزی‌های بانکی
    org_unit         = Column(String(80))               # واحد سازمانی (استان/واحد محل خدمت)

    father_name      = Column(String(80))
    birth_date       = Column(String(20))
    birth_place      = Column(String(60))
    marital_status   = Column(String(20))
    landline         = Column(String(15))
    address          = Column(Text)
    postal_code      = Column(String(10))
    occupation       = Column(String(80))
    email            = Column(String(120))
    bank_name        = Column(String(60))
    account_number   = Column(String(30))
    iban             = Column(String(30))
    bale_chat_id     = Column(String(40))
    bale_link_code   = Column(String(10))
    bale_link_code_expires_at = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    # فقط دفترچه‌های فعال (soft-delete شده‌ها مخفی هستند)
    booklets      = relationship(
        "Booklet",
        primaryjoin="and_(User.id == Booklet.owner_id, Booklet.deleted_at.is_(None))",
        back_populates="owner", lazy="select", viewonly=False,
    )
    payments      = relationship("Payment",      back_populates="user",   lazy="select")
    notifications = relationship("Notification", back_populates="user",   lazy="select")

    # فیلدهای الزامی برای کامل بودن واقعی پروفایل — منبع واحد؛ فراموشی
    # تنظیم درست profile_complete در مسیرهای مختلف ساخت کاربر (افزودن دستی،
    # ورود اکسل، ثبت‌نام از طریق انتقال) دیگر باعث دورزدن قفل پنل نمی‌شود
    # چون کامل بودن همیشه زنده از روی همین فیلدها محاسبه می‌شود.
    REQUIRED_PROFILE_FIELDS = (
        "first_name", "last_name", "father_name", "birth_date", "birth_place",
        "marital_status", "occupation", "phone", "emergency_phone", "postal_code", "address", "bank_name",
    )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def missing_profile_fields(self):
        return [f for f in self.REQUIRED_PROFILE_FIELDS if not str(getattr(self, f) or "").strip()]

    def is_profile_complete(self):
        return not self.missing_profile_fields()

    def to_dict(self):
        d = {c.key: getattr(self, c.key)
             for c in self.__table__.columns
             if c.key != "password_hash"}
        d["full_name"] = self.full_name
        d["profile_actually_complete"] = self.is_profile_complete()
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Project  (پروژه — داینامیک، هر پروژه N دفترچه دارد)
# ─────────────────────────────────────────────────────────────────────────────
class Project(Base):
    """پروژه ساخت‌وساز تعاونی — هر پروژه شامل چند دفترچه (واحد/سهم) است."""
    __tablename__ = "projects"

    id              = Column(Integer, primary_key=True)
    name            = Column(String(200), nullable=False)          # نام پروژه
    description     = Column(Text)
    address         = Column(Text)                                  # آدرس پروژه
    location        = Column(String(200))                           # منطقه/شهرک
    total_booklets  = Column(Integer, default=0)                    # تعداد کل دفترچه‌ها
    start_date      = Column(String(20))
    end_date        = Column(String(20))
    status          = Column(String(20), default="active")          # active|completed|upcoming
    image_path      = Column(String(260))
    map_lat         = Column(String(20))   # عرض جغرافیایی گوگل مپ
    map_lon         = Column(String(20))   # طول جغرافیایی گوگل مپ
    order           = Column(Integer, default=0)
    active          = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    booklets = relationship(
        "Booklet",
        primaryjoin="and_(Project.id == Booklet.project_id, Booklet.deleted_at.is_(None))",
        back_populates="project", lazy="select",
    )
    members  = relationship("ProjectMember", back_populates="project", order_by="ProjectMember.order", lazy="select")
    gallery  = relationship("ProjectGallery", back_populates="project", order_by="ProjectGallery.order", lazy="select")

    def to_dict(self):
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}


# ─────────────────────────────────────────────────────────────────────────────
# ProjectGallery  (گالری تصویر و ویدیو برای هر پروژه)
# ─────────────────────────────────────────────────────────────────────────────
class ProjectGallery(Base):
    """آیتم گالری تصویر/ویدیوی یک پروژه."""
    __tablename__ = "project_gallery"

    id         = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    file_path  = Column(String(260), nullable=False)
    file_type  = Column(String(10), default='image')   # image | video
    caption    = Column(String(200))
    order      = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="gallery")

    def to_dict(self):
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}


# ─────────────────────────────────────────────────────────────────────────────
# ProjectMember  (اعضای هیئت هر پروژه)
# ─────────────────────────────────────────────────────────────────────────────
class ProjectMember(Base):
    """عضو هیئت اجرایی/امنای یک پروژه (نمایشی، غیر از عضویت تعاونی کاربران)."""
    __tablename__ = "project_members"

    id          = Column(Integer, primary_key=True)
    project_id  = Column(Integer, ForeignKey("projects.id"), nullable=False)
    role        = Column(String(60),  nullable=False)   # مدیر اجرایی | رئیس هیئت اجرایی | مدیر هیئت امنا
    full_name   = Column(String(120), nullable=False)
    phone       = Column(String(15))
    photo_path  = Column(String(260))                   # عکس عضو
    order       = Column(Integer, default=0)            # ترتیب نمایش

    project = relationship("Project", back_populates="members")

    def to_dict(self):
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}


# ─────────────────────────────────────────────────────────────────────────────
# Booklet  (دفترچه — به پروژه وصل است، نوع: تمام‌سهم یا نیم‌سهم)
# ─────────────────────────────────────────────────────────────────────────────
class Booklet(Base):
    """دفترچه (سهم/واحد) متعلق به یک پروژه و یک مالک — واحد اصلی مالکیت در سامانه."""
    __tablename__ = "booklets"
    # شماره قرارداد/کد فقط باید در همان پروژه یکتا باشد، نه بین همه پروژه‌ها —
    # دو پروژه مختلف می‌توانند هر دو یک شماره قرارداد ۳ داشته باشند
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_booklets_project_code"),)

    id              = Column(Integer, primary_key=True)
    code            = Column(String(30), nullable=False)                 # کد داخلی ZNJ-xxx
    serial          = Column(Integer)                                    # شماره ترتیبی در پروژه
    booklet_number  = Column(String(30), default="")                     # شماره دفترچه دستی
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False)
    owner_id        = Column(Integer, ForeignKey("users.id"),    nullable=False)

    share_type  = Column(String(20), default="full")   # full=تمام‌سهم | half=نیم‌سهم
    contract_no = Column(String(60), default="")       # شماره قرارداد
    contract_date = Column(String(20), default="")     # تاریخ قرارداد
    contract_amount = Column(BigInteger,  default=0)      # مبلغ قرارداد (ریال)
    notes       = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)
    # Soft delete — رکورد مالکیت هرگز فیزیکی حذف نمی‌شود تا سابقه مالی حفظ بماند
    deleted_at  = Column(DateTime, nullable=True)

    owner   = relationship("User",    back_populates="booklets")
    project = relationship("Project", back_populates="booklets")
    payments = relationship("Payment", back_populates="booklet", lazy="select")

    def to_dict(self):
        d = {c.key: getattr(self, c.key) for c in self.__table__.columns}
        d["project_name"]  = self.project.name  if self.project else ""
        d["owner_name"]    = self.owner.full_name if self.owner  else ""
        d["share_label"]   = "تمام‌سهم" if self.share_type == "full" else "نیم‌سهم"
        return d


# ─────────────────────────────────────────────────────────────────────────────
# TransferRequest / TransferHistory
# ─────────────────────────────────────────────────────────────────────────────
class TransferRequest(Base):
    """درخواست انتقال مالکیت یک دفترچه به مالک جدید (در انتظار تأیید مدیر)."""
    __tablename__ = "transfer_requests"

    id                      = Column(Integer, primary_key=True)
    booklet_id              = Column(Integer, ForeignKey("booklets.id"), nullable=False)
    requester_id            = Column(Integer, ForeignKey("users.id"),   nullable=False)
    new_owner_first_name    = Column(String(60),  nullable=False, default="")
    new_owner_last_name     = Column(String(60),  nullable=False, default="")
    new_owner_national_code = Column(String(10),  nullable=False)
    new_owner_phone         = Column(String(15),  nullable=False)
    note                    = Column(Text)
    status                  = Column(String(20), default="pending")
    receipt_path            = Column(String(260), default="")
    agreement_path          = Column(String(260), default="")
    sana_form_path          = Column(String(260), default="")
    id_first_page_path      = Column(String(260), default="")
    national_front_path     = Column(String(260), default="")
    national_back_path      = Column(String(260), default="")
    extra_photo_path        = Column(String(260), default="")   # عکس اضافی اختیاری
    created_at              = Column(DateTime, default=datetime.utcnow)
    reviewed_at             = Column(DateTime)
    review_note             = Column(Text)

    booklet   = relationship("Booklet")
    requester = relationship("User", foreign_keys=[requester_id])

    @property
    def new_owner_full_name(self):
        return f"{self.new_owner_first_name} {self.new_owner_last_name}".strip()


class TransferHistory(Base):
    """تاریخچه ثبت‌شده و قطعیِ انتقال مالکیت یک دفترچه (پس از تأیید درخواست)."""
    __tablename__ = "transfer_history"

    id           = Column(Integer, primary_key=True)
    booklet_id   = Column(Integer, ForeignKey("booklets.id"), nullable=False)
    from_user_id = Column(Integer, ForeignKey("users.id"),   nullable=False)
    to_user_id   = Column(Integer, ForeignKey("users.id"),   nullable=False)
    date         = Column(DateTime, default=datetime.utcnow)
    request_id   = Column(Integer)

    booklet   = relationship("Booklet", foreign_keys=[booklet_id])
    from_user = relationship("User",    foreign_keys=[from_user_id])
    to_user   = relationship("User",    foreign_keys=[to_user_id])


# ─────────────────────────────────────────────────────────────────────────────
# Announcement
# ─────────────────────────────────────────────────────────────────────────────
class Announcement(Base):
    """اطلاعیه/خبر — قابل انتشار عمومی یا محدود به یک پروژه، با زمان‌بندی انتشار/انقضا."""
    __tablename__ = "announcements"

    id         = Column(Integer,     primary_key=True)
    title      = Column(String(200), nullable=False)
    body       = Column(Text,        nullable=False)
    image_path = Column(String(260))
    author_id  = Column(Integer,     ForeignKey("users.id"))
    author     = Column(String(80),  default="")
    date       = Column(DateTime,    default=datetime.utcnow)
    project_id = Column(Integer,     ForeignKey("projects.id"), nullable=True)
    pub_date   = Column(DateTime,    nullable=True)   # تاریخ انتشار (NULL = فوری)
    expires_at = Column(DateTime,    nullable=True)   # تاریخ انقضا (NULL = بدون انقضا)

    project = relationship("Project")
    media   = relationship("AnnouncementMedia", back_populates="announcement", order_by="AnnouncementMedia.order", lazy="select")


# ─────────────────────────────────────────────────────────────────────────────
# AnnouncementMedia  (گالری اطلاعیه)
# ─────────────────────────────────────────────────────────────────────────────
class AnnouncementMedia(Base):
    """آیتم گالری تصویر/ویدیوی یک اطلاعیه."""
    __tablename__ = "announcement_media"

    id              = Column(Integer, primary_key=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id"), nullable=False)
    file_path       = Column(String(260), nullable=False)
    file_type       = Column(String(10), default='image')  # image | video
    caption         = Column(String(200))
    order           = Column(Integer, default=0)
    created_at      = Column(DateTime, default=datetime.utcnow)

    announcement = relationship("Announcement", back_populates="media")

    def to_dict(self):
        return {c.key: getattr(self, c.key) for c in self.__table__.columns}


# ─────────────────────────────────────────────────────────────────────────────
# PaymentPlan  (هر پروژه طرح پرداخت مخصوص خودش دارد)
# ─────────────────────────────────────────────────────────────────────────────
class PaymentPlan(Base):
    """طرح پرداخت اقساطی — می‌تواند مخصوص یک پروژه یا عمومی (project_id=NULL) باشد."""
    __tablename__ = "payment_plans"

    id           = Column(Integer,     primary_key=True)
    project_id   = Column(Integer,     ForeignKey("projects.id"))   # اختیاری — اگر NULL برای همه
    title        = Column(String(200), nullable=False)
    total_amount = Column(BigInteger,  nullable=False)
    installments = Column(Integer,     nullable=False)
    start_date   = Column(String(20),  nullable=False)
    description  = Column(Text)
    created_at   = Column(DateTime,    default=datetime.utcnow)

    project  = relationship("Project")
    payments = relationship("Payment", back_populates="plan", lazy="select")


# ─────────────────────────────────────────────────────────────────────────────
# Payment
# ─────────────────────────────────────────────────────────────────────────────
class Payment(Base):
    """قسط پرداخت یک عضو — می‌تواند به یک دفترچه و/یا یک طرح پرداخت مرتبط باشد."""
    __tablename__ = "payments"

    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id"),        nullable=False)
    booklet_id   = Column(Integer, ForeignKey("booklets.id"))
    plan_id      = Column(Integer, ForeignKey("payment_plans.id"))
    amount       = Column(BigInteger, nullable=False)
    due_date     = Column(String(20), nullable=False)
    paid_date    = Column(String(20))
    status       = Column(String(20), default="unpaid")   # unpaid|paid|overdue
    description  = Column(Text)
    receipt_path = Column(String(260))
    created_at   = Column(DateTime, default=datetime.utcnow)

    user    = relationship("User",        back_populates="payments")
    booklet = relationship("Booklet",     back_populates="payments")
    plan    = relationship("PaymentPlan", back_populates="payments")


# ─────────────────────────────────────────────────────────────────────────────
# Notification
# ─────────────────────────────────────────────────────────────────────────────
class Notification(Base):
    """اعلان داخل‌سامانه‌ای برای یک کاربر (بج ناخوانده در هدر پنل)."""
    __tablename__ = "notifications"

    id         = Column(Integer,     primary_key=True)
    user_id    = Column(Integer,     ForeignKey("users.id"), nullable=False)
    title      = Column(String(200), nullable=False)
    body       = Column(Text,        nullable=False)
    type       = Column(String(20),  default="info")
    read       = Column(Boolean,     default=False)
    created_at = Column(DateTime,    default=datetime.utcnow)

    user = relationship("User", back_populates="notifications")


# ─────────────────────────────────────────────────────────────────────────────
# Slide  (اسلایدهای صفحه عمومی)
# ─────────────────────────────────────────────────────────────────────────────
class Slide(Base):
    """اسلاید صفحه اصلی سایت عمومی (تصویر یا ویدیو)."""
    __tablename__ = "slides"

    id         = Column(Integer,     primary_key=True)
    title      = Column(String(200), nullable=False)
    subtitle   = Column(Text)
    image_path = Column(String(260))
    video_path = Column(String(260))                   # ویدیو (جایگزین تصویر)
    media_type = Column(String(10),  default='image')  # image | video
    bg_color   = Column(String(20),  default="#1E2A42")
    order      = Column(Integer,     default=0)
    active     = Column(Boolean,     default=True)
    created_at = Column(DateTime,    default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# SiteSetting
# ─────────────────────────────────────────────────────────────────────────────
class SiteSetting(Base):
    """جدول کلید/مقدار برای تنظیمات عمومی سایت (key-value store ساده)."""
    __tablename__ = "site_settings"

    key   = Column(String(80), primary_key=True)
    value = Column(Text, nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# CoopAccount — حساب‌های دریافت‌کننده وجوه تعاونی (حساب مدیر، هیئت امنا، ...)
# ─────────────────────────────────────────────────────────────────────────────
class CoopAccount(Base):
    """حساب بانکی دریافت‌کننده وجوه تعاونی (حساب مدیر اجرایی، هیئت امنا و ...)."""
    __tablename__ = "coop_accounts"

    id             = Column(Integer, primary_key=True)
    holder_name    = Column(String(120), nullable=False)   # نام صاحب حساب
    holder_role    = Column(String(80),  default="")       # سمت: مدیر اجرایی، هیئت امنا، ...
    bank_name      = Column(String(60),  default="")
    account_number = Column(String(30),  default="")
    card_number    = Column(String(20),  default="")
    iban           = Column(String(30),  default="")
    active         = Column(Boolean, default=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        d = {c.key: getattr(self, c.key) for c in self.__table__.columns}
        d["created_at"] = self.created_at.isoformat() if self.created_at else None
        return d


# ─────────────────────────────────────────────────────────────────────────────
# DepositVoucher — سند واریز: چه کسی، چه زمانی، چه مبلغی به کدام حساب واریز کرد
# اسناد مالی حذف نمی‌شوند — فقط «ابطال» با ثبت دلیل (برای حسابرسی)
# ─────────────────────────────────────────────────────────────────────────────
class DepositVoucher(Base):
    """سند واریز — ثبت رسمی اینکه چه کسی چه مبلغی به کدام حساب تعاونی واریز کرد."""
    __tablename__ = "deposit_vouchers"

    id            = Column(Integer, primary_key=True)
    number        = Column(Integer, unique=True)                       # شماره سند (سریال)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    payer_name    = Column(String(120), default="")                    # اگر واریزکننده عضو نبود
    account_id    = Column(Integer, ForeignKey("coop_accounts.id"), nullable=False)
    amount        = Column(BigInteger, nullable=False)                 # ریال
    deposit_date  = Column(String(20), nullable=False)                 # تاریخ شمسی 1404/05/01
    deposit_time  = Column(String(10), default="")                     # ساعت 14:30
    method        = Column(String(30), default="card")                 # card|transfer|cash|cheque|other
    reference_no  = Column(String(60), default="")                     # شماره پیگیری/سند بانکی
    description   = Column(Text)                                       # شرح سند
    receipt_path  = Column(String(260))
    payment_id    = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)  # لینک به قسط (اختیاری)
    status        = Column(String(20), default="active")               # active | voided
    void_reason   = Column(Text)
    voided_at     = Column(DateTime, nullable=True)
    created_by    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

    # فیلدهای مخصوص واردات صورت‌حساب بانکی خام (تطبیق خودکار با شناسه واریز عضو)
    source              = Column(String(20), default="manual")  # manual | bank_import
    branch_code         = Column(String(20), default="")
    branch_name         = Column(String(80), default="")
    channel             = Column(String(20), default="")        # TELLER, ATM, ...
    bank_balance_after  = Column(BigInteger, nullable=True)      # مانده حساب بلافاصله پس از این تراکنش (طبق صورت‌حساب بانک)

    # کدینگ نوع واریزی — برای تفکیک در جستجو/گزارش‌ها
    category = Column(String(20), default="member_deposit")  # member_deposit | bank_interest | other

    user    = relationship("User",        foreign_keys=[user_id])
    account = relationship("CoopAccount", foreign_keys=[account_id])
    creator = relationship("User",        foreign_keys=[created_by])

    def to_dict(self):
        return {
            "id": self.id, "number": self.number,
            "user_id": self.user_id,
            "payer_name": self.user.full_name if self.user else (self.payer_name or ""),
            "account_id": self.account_id,
            "account_label": (f"{self.account.holder_name}"
                              + (f" ({self.account.holder_role})" if self.account.holder_role else "")
                              ) if self.account else "",
            "amount": self.amount,
            "deposit_date": self.deposit_date, "deposit_time": self.deposit_time or "",
            "method": self.method, "reference_no": self.reference_no or "",
            "description": self.description or "",
            "receipt_path": self.receipt_path or "",
            "payment_id": self.payment_id,
            "status": self.status, "void_reason": self.void_reason or "",
            "created_by_name": self.creator.full_name if self.creator else "",
            "created_at": self.created_at.isoformat(),
            "source": self.source or "manual",
            "branch_code": self.branch_code or "", "branch_name": self.branch_name or "",
            "channel": self.channel or "", "bank_balance_after": self.bank_balance_after,
            "category": self.category or "member_deposit",
            "matched": bool(self.user_id),
        }


# ─────────────────────────────────────────────────────────────────────────────
# VoucherAllocation — تخصیص (بخشی از) یک سند واریز به یک قسط پرداخت
# یک سند می‌تواند بین چند قسط تقسیم شود؛ یک قسط می‌تواند از چند سند پر شود.
# ─────────────────────────────────────────────────────────────────────────────
class VoucherAllocation(Base):
    """تخصیص بخشی از مبلغ یک سند واریز به یک قسط پرداخت مشخص (رابطه چند-به-چند)."""
    __tablename__ = "voucher_allocations"

    id         = Column(Integer, primary_key=True)
    voucher_id = Column(Integer, ForeignKey("deposit_vouchers.id", ondelete="CASCADE"), nullable=False)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    amount     = Column(BigInteger, nullable=False)   # ریال تخصیص‌یافته
    created_at = Column(DateTime, default=datetime.utcnow)

    voucher = relationship("DepositVoucher", foreign_keys=[voucher_id])
    payment = relationship("Payment",        foreign_keys=[payment_id])

    def to_dict(self):
        return {"id": self.id, "voucher_id": self.voucher_id,
                "payment_id": self.payment_id, "amount": self.amount}


# ─────────────────────────────────────────────────────────────────────────────
# ExpenseVoucher — سند هزینه (خروجی وجه): از کدام حساب، بابت چه، به چه کسی
# متقارن سند واریز — موجودی حساب = واریزی‌ها − هزینه‌ها
# ─────────────────────────────────────────────────────────────────────────────
class ExpenseVoucher(Base):
    """سند هزینه (خروج وجه از یک حساب تعاونی) — متقارن با DepositVoucher."""
    __tablename__ = "expense_vouchers"

    id           = Column(Integer, primary_key=True)
    number       = Column(Integer, unique=True)                       # شماره سند سریالی
    account_id   = Column(Integer, ForeignKey("coop_accounts.id"), nullable=False)  # پرداخت از کدام حساب
    project_id   = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    category     = Column(String(30), default="other")                # land|contractor|admin|utility|other
    payee        = Column(String(120), default="")                    # دریافت‌کننده
    amount       = Column(BigInteger, nullable=False)
    spend_date   = Column(String(20), nullable=False)
    spend_time   = Column(String(10), default="")
    method       = Column(String(30), default="transfer")
    reference_no = Column(String(60), default="")
    description  = Column(Text)
    receipt_path = Column(String(260))
    status       = Column(String(20), default="active")               # active|voided
    void_reason  = Column(Text)
    voided_at    = Column(DateTime, nullable=True)
    created_by   = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)

    account = relationship("CoopAccount", foreign_keys=[account_id])
    project = relationship("Project",     foreign_keys=[project_id])
    creator = relationship("User",        foreign_keys=[created_by])

    def to_dict(self):
        return {
            "id": self.id, "number": self.number,
            "account_id": self.account_id,
            "account_label": (f"{self.account.holder_name}"
                              + (f" ({self.account.holder_role})" if self.account.holder_role else "")
                              ) if self.account else "",
            "project_id": self.project_id,
            "project_name": self.project.name if self.project else "",
            "category": self.category, "payee": self.payee or "",
            "amount": self.amount,
            "spend_date": self.spend_date, "spend_time": self.spend_time or "",
            "method": self.method, "reference_no": self.reference_no or "",
            "description": self.description or "",
            "receipt_path": self.receipt_path or "",
            "status": self.status, "void_reason": self.void_reason or "",
            "created_by_name": self.creator.full_name if self.creator else "",
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# MemberLedgerEntry — سند دستی بدهکار/بستانکار در کارت حساب عضو
# برای مواردی که خودکار از قسط/واریز نمی‌آیند: جریمه دیرکرد، تخفیف، اصلاح حساب و ...
# مثل سایر اسناد مالی حذف نمی‌شود — فقط «ابطال» با ثبت دلیل (برای حسابرسی)
# ─────────────────────────────────────────────────────────────────────────────
class MemberLedgerEntry(Base):
    """سند دستی بدهکار/بستانکار در کارت حساب یک عضو (جریمه، تخفیف، اصلاح حساب و ...)."""
    __tablename__ = "member_ledger_entries"

    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entry_type  = Column(String(10), nullable=False)   # debit=بدهکار (به نفع تعاونی) | credit=بستانکار (به نفع عضو)
    amount      = Column(BigInteger, nullable=False)
    entry_date  = Column(String(20), nullable=False)   # تاریخ شمسی
    title       = Column(String(200), nullable=False)  # شرح کوتاه — مثلاً «جریمه دیرکرد» یا «تخفیف نقدی»
    note        = Column(Text)
    status      = Column(String(20), default="active")  # active | voided
    void_reason = Column(Text)
    voided_at   = Column(DateTime, nullable=True)
    created_by  = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    user    = relationship("User", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[created_by])

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id,
            "entry_type": self.entry_type, "amount": self.amount,
            "entry_date": self.entry_date, "title": self.title,
            "note": self.note or "",
            "status": self.status, "void_reason": self.void_reason or "",
            "created_by_name": self.creator.full_name if self.creator else "",
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# MemberDocument — آرشیو اسناد هر عضو (قرارداد امضاشده، مدارک هویتی، ...)
# ─────────────────────────────────────────────────────────────────────────────
class MemberDocument(Base):
    """سند آرشیوشده مربوط به یک عضو (قرارداد امضاشده، مدرک هویتی و ...)."""
    __tablename__ = "member_documents"

    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title       = Column(String(200), nullable=False)              # عنوان سند
    doc_type    = Column(String(40),  default="other")             # contract|identity|financial|other
    file_path   = Column(String(260), nullable=False)
    note        = Column(Text)
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id,
            "title": self.title, "doc_type": self.doc_type,
            "file_path": self.file_path, "note": self.note or "",
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# PasswordResetCode — کد بازیابی رمز (روی دیتابیس، امن برای چند-worker)
# ─────────────────────────────────────────────────────────────────────────────
class PasswordResetCode(Base):
    """کد یک‌بارمصرف بازیابی رمز عبور — روی دیتابیس ذخیره می‌شود (نه حافظه) تا با چند-worker امن باشد."""
    __tablename__ = "password_reset_codes"

    id         = Column(Integer, primary_key=True)
    identifier = Column(String(40), index=True, nullable=False)   # کد ملی / نام کاربری
    code_hash  = Column(String(256), nullable=False)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    verified   = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# ActivityLog — لاگ فعالیت‌های کاربران
# ─────────────────────────────────────────────────────────────────────────────
class ActivityLog(Base):
    """لاگ فعالیت‌های امنیتی/کاربری سامانه (ورود، ایجاد/ویرایش رکوردها و ...)."""
    __tablename__ = "activity_logs"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action     = Column(String(80), nullable=False)   # e.g. "login", "transfer_request", ...
    category   = Column(String(40), nullable=False, default="general")
    detail     = Column(Text, nullable=True)
    ip         = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            'id':         self.id,
            'user_id':    self.user_id,
            'user_name':  self.user.full_name if self.user else 'سیستم',
            'user_role':  self.user.role if self.user else '',
            'action':     self.action,
            'category':   self.category,
            'detail':     self.detail or '',
            'ip':         self.ip or '',
            'created_at': self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Ticket — سیستم تیکتینگ
# ─────────────────────────────────────────────────────────────────────────────
TICKET_CATS    = ('financial', 'transfer', 'technical', 'general')
TICKET_PRIOS   = ('low', 'normal', 'high', 'urgent')
TICKET_STATUSES = ('open', 'in_progress', 'waiting', 'resolved', 'closed')

class Ticket(Base):
    """تیکت پشتیبانی — می‌تواند مستقل باشد یا از یک درخواست خرید بازار ساخته شده باشد."""
    __tablename__ = "tickets"

    id          = Column(Integer, primary_key=True)
    number      = Column(Integer, unique=True)          # human-readable #1001, #1002 ...
    subject     = Column(String(200), nullable=False)
    category    = Column(String(40), default='general')
    priority    = Column(String(20), default='normal')
    status      = Column(String(30), default='open')
    creator_id  = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    assigned_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # اگر این تیکت از یک درخواست خرید در بازار نقل‌وانتقال ساخته شده — برای اینکه
    # فروشندهٔ آگهی هم (نه فقط سازنده تیکت) بتواند آن را ببیند، بدون نیاز به
    # سیستم Ticketing جدید یا مفهوم «گیرنده» که در مدل فعلی وجود ندارد
    listing_id  = Column(Integer, ForeignKey("marketplace_listings.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at   = Column(DateTime, nullable=True)

    creator  = relationship("User", foreign_keys=[creator_id])
    assigned = relationship("User", foreign_keys=[assigned_id])
    messages = relationship("TicketMessage", back_populates="ticket",
                            order_by="TicketMessage.created_at", cascade="all, delete-orphan")

    def to_dict(self, with_messages=False):
        d = {
            'id':            self.id,
            'number':        self.number,
            'subject':       self.subject,
            'category':      self.category,
            'priority':      self.priority,
            'status':        self.status,
            'creator_id':    self.creator_id,
            'creator_name':  self.creator.full_name if self.creator else '',
            'assigned_name': self.assigned.full_name if self.assigned else '',
            'created_at':    self.created_at.isoformat(),
            'updated_at':    self.updated_at.isoformat(),
            'closed_at':     self.closed_at.isoformat() if self.closed_at else None,
            'message_count': len(self.messages),
            'last_reply_at': self.messages[-1].created_at.isoformat() if self.messages else None,
        }
        if with_messages:
            d['messages'] = [m.to_dict() for m in self.messages]
        return d


class TicketMessage(Base):
    """یک پیام در مکالمه یک تیکت (از طرف عضو یا مدیر)."""
    __tablename__ = "ticket_messages"

    id         = Column(Integer, primary_key=True)
    ticket_id  = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"))
    sender_id  = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body       = Column(Text, nullable=False)
    is_admin   = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])

    def to_dict(self):
        return {
            'id':          self.id,
            'ticket_id':   self.ticket_id,
            'sender_id':   self.sender_id,
            'sender_name': self.sender.full_name if self.sender else 'سیستم',
            'body':        self.body,
            'is_admin':    self.is_admin,
            'created_at':  self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Form Builder
# ─────────────────────────────────────────────────────────────────────────────
class Form(Base):
    """فرم پویا (فرم‌ساز) — می‌تواند چندمرحله‌ای، عمومی یا محدود به لیست سفید افراد باشد."""
    __tablename__ = "forms"

    id              = Column(Integer, primary_key=True)
    title           = Column(String(200), nullable=False)
    description     = Column(Text)
    slug            = Column(String(100), unique=True)
    status          = Column(String(20), default="draft")       # draft|published|archived
    is_public       = Column(Boolean, default=True)
    multi_step      = Column(Boolean, default=False)
    allow_edit      = Column(Boolean, default=False)
    max_submissions = Column(Integer, default=0)                # 0 = unlimited
    expires_at      = Column(DateTime, nullable=True)
    success_msg     = Column(Text)
    restrict_access = Column(Boolean, default=False)             # فقط افراد لیست‌شده مجاز به تکمیل هستند
    created_by      = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator     = relationship("User", foreign_keys=[created_by])
    steps       = relationship("FormStep", back_populates="form",
                               order_by="FormStep.order", cascade="all, delete-orphan")
    submissions = relationship("FormSubmission", back_populates="form",
                               cascade="all, delete-orphan")
    allowed_people = relationship("FormAllowedPerson", back_populates="form",
                               cascade="all, delete-orphan")

    def to_dict(self):
        d = {c.key: getattr(self, c.key) for c in self.__table__.columns}
        d['step_count']       = len(self.steps)
        d['submission_count'] = len(self.submissions)
        d['creator_name']     = self.creator.full_name if self.creator else ''
        if d.get('expires_at') and hasattr(d['expires_at'], 'isoformat'):
            d['expires_at'] = d['expires_at'].isoformat()
        return d


class FormStep(Base):
    """یک مرحله از یک فرم چندمرحله‌ای؛ شامل چند فیلد."""
    __tablename__ = "form_steps"

    id          = Column(Integer, primary_key=True)
    form_id     = Column(Integer, ForeignKey("forms.id", ondelete="CASCADE"), nullable=False)
    title       = Column(String(200), nullable=False, default="")
    description = Column(Text)
    order       = Column(Integer, default=0)

    form   = relationship("Form", back_populates="steps")
    fields = relationship("FormField", back_populates="step",
                          order_by="FormField.order", cascade="all, delete-orphan")

    def to_dict(self):
        d = {c.key: getattr(self, c.key) for c in self.__table__.columns}
        d['fields'] = [f.to_dict() for f in self.fields]
        return d


class FormField(Base):
    """یک فیلد ورودی در یک مرحله از فرم؛ تنظیمات/اعتبارسنجی/شرط نمایش به‌صورت JSON در متن ذخیره می‌شود."""
    __tablename__ = "form_fields"

    id          = Column(Integer, primary_key=True)
    step_id     = Column(Integer, ForeignKey("form_steps.id", ondelete="CASCADE"), nullable=False)
    form_id     = Column(Integer, ForeignKey("forms.id",      ondelete="CASCADE"), nullable=False)
    field_type  = Column(String(40), nullable=False)
    label       = Column(String(200), nullable=False)
    placeholder = Column(String(200))
    help_text   = Column(Text)
    required    = Column(Boolean, default=False)
    options     = Column(Text)       # JSON array for select/radio/checkbox
    validation  = Column(Text)       # JSON rules
    conditions  = Column(Text)       # JSON conditional logic
    default_val = Column(Text)
    order       = Column(Integer, default=0)
    width       = Column(String(10), default='full')   # full|half|third

    step = relationship("FormStep", back_populates="fields")

    def to_dict(self):
        import json
        d = {c.key: getattr(self, c.key) for c in self.__table__.columns}
        for k in ('options', 'validation', 'conditions'):
            if d[k]:
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        return d


class FormSubmission(Base):
    """یک بار ارسال (پُر شدن) یک فرم، توسط کاربر لاگین‌شده یا ناشناس."""
    __tablename__ = "form_submissions"

    id           = Column(Integer, primary_key=True)
    form_id      = Column(Integer, ForeignKey("forms.id", ondelete="CASCADE"), nullable=False)
    submitter_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status       = Column(String(20), default="submitted")  # submitted|reviewing|approved|rejected
    ip_address   = Column(String(45))
    note         = Column(Text)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    form      = relationship("Form", back_populates="submissions")
    submitter = relationship("User", foreign_keys=[submitter_id])
    values    = relationship("FormSubmissionValue", back_populates="submission",
                             cascade="all, delete-orphan")
    history   = relationship("FormSubmissionHistory", back_populates="submission",
                             order_by="FormSubmissionHistory.created_at", cascade="all, delete-orphan")

    def to_dict(self, with_values=False):
        d = {c.key: getattr(self, c.key) for c in self.__table__.columns}
        d['submitter_name'] = self.submitter.full_name if self.submitter else 'ناشناس'
        d['form_title']     = self.form.title if self.form else ''
        if with_values:
            d['values'] = {v.field_id: v.value for v in self.values}
        return d


class FormSubmissionValue(Base):
    """مقدار وارد‌شده برای یک فیلد مشخص در یک ارسال فرم."""
    __tablename__ = "form_submission_values"

    id            = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id", ondelete="CASCADE"), nullable=False)
    field_id      = Column(Integer, ForeignKey("form_fields.id",      ondelete="SET NULL"), nullable=True)
    field_label   = Column(String(200))
    value         = Column(Text)

    submission = relationship("FormSubmission", back_populates="values")
    field      = relationship("FormField")


class FormSubmissionHistory(Base):
    """تاریخچه تغییر وضعیت/بررسی یک ارسال فرم (مثلاً تأیید/رد توسط مدیر)."""
    __tablename__ = "form_submission_history"

    id            = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id", ondelete="CASCADE"), nullable=False)
    actor_id      = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action        = Column(String(80), nullable=False)
    note          = Column(Text)
    created_at    = Column(DateTime, default=datetime.utcnow)

    submission = relationship("FormSubmission", back_populates="history")
    actor      = relationship("User", foreign_keys=[actor_id])


# ─────────────────────────────────────────────────────────────────────────────
# FormAllowedPerson — لیست سفید افراد مجاز به تکمیل یک فرم اختصاصی
# تطبیق بر اساس کد ملی و/یا موبایل (هر کدام که وارد شود کافیست)
# ─────────────────────────────────────────────────────────────────────────────
class FormAllowedPerson(Base):
    """لیست سفید افراد مجاز به تکمیل یک فرم محدودشده (تطبیق بر اساس کد ملی و/یا موبایل)."""
    __tablename__ = "form_allowed_people"

    id             = Column(Integer, primary_key=True)
    form_id        = Column(Integer, ForeignKey("forms.id", ondelete="CASCADE"), nullable=False)
    national_code  = Column(String(10), default="")
    phone          = Column(String(15), default="")
    full_name      = Column(String(120), default="")
    used_at        = Column(DateTime, nullable=True)   # زمانی که این فرد فرم را ارسال کرد
    created_at     = Column(DateTime, default=datetime.utcnow)

    form = relationship("Form", back_populates="allowed_people")

    def to_dict(self):
        return {c.key: (v.isoformat() if hasattr(v, 'isoformat') else v)
                for c, v in ((c, getattr(self, c.key)) for c in self.__table__.columns)}


# ─────────────────────────────────────────────────────────────────────────────
# Marketplace — بازار خرید و فروش دفترچه‌ها/امتیازات اعضا
# ─────────────────────────────────────────────────────────────────────────────
class MarketplaceListing(Base):
    """آگهی فروش یک دفترچه در بازار داخلی — ماشین‌حالت وضعیت فقط از طریق API سرور تغییر می‌کند."""
    __tablename__ = "marketplace_listings"

    # ماشین حالت — انتقال‌ها فقط از طریق منطق سرور (marketplace API) انجام می‌شود
    STATUS_DRAFT             = "draft"
    STATUS_WAITING_PAYMENT   = "waiting_payment"
    STATUS_PAYMENT_REVIEW    = "payment_review"
    STATUS_ADMIN_REVIEW      = "admin_review"
    STATUS_PUBLISHED         = "published"
    STATUS_REJECTED          = "rejected"
    STATUS_EXPIRED           = "expired"
    STATUS_SOLD              = "sold"
    STATUS_CANCELLED         = "cancelled"
    STATUS_DISABLED          = "disabled"

    CONTACT_PHONE   = "phone"
    CONTACT_REQUEST = "request"
    CONTACT_BOTH    = "both"

    id            = Column(Integer, primary_key=True)
    code          = Column(String(45), unique=True, nullable=False)   # مثال: TM-1405-00125
    slug          = Column(String(160), unique=True, nullable=False)

    seller_id     = Column(Integer, ForeignKey("users.id"),    nullable=False)
    booklet_id    = Column(Integer, ForeignKey("booklets.id"), nullable=False)
    project_id    = Column(Integer, ForeignKey("projects.id"), nullable=False)  # denormalized برای فیلتر سریع

    title         = Column(String(200), nullable=False)
    unit_type     = Column(String(150), default="")     # نوع دفترچه/امتیاز (نمایشی؛ پیش‌فرض از share_type دفترچه)
    area          = Column(Integer, nullable=True)       # متراژ (متر مربع) — اختیاری
    price         = Column(BigInteger, nullable=False)    # قیمت فروش (تومان)
    negotiable    = Column(Boolean, default=False)
    sale_terms    = Column(Text)
    description   = Column(Text)

    contact_phone  = Column(String(30), default="")
    contact_method = Column(String(10), default=CONTACT_REQUEST)   # phone | request | both

    status         = Column(String(20), default=STATUS_DRAFT, nullable=False)
    reject_reason  = Column(Text)

    # Snapshot هزینه ثبت آگهی — مقدار واقعی هنگام ایجاد، مستقل از تغییرات بعدی Setting
    fee_required  = Column(Boolean, default=True)
    fee_amount    = Column(BigInteger, default=0)   # تومان — snapshot

    payment_receipt_path   = Column(String(260), default="")
    payment_date           = Column(String(20),  default="")
    payment_tracking_code  = Column(String(60),  default="")
    payment_reviewed_by    = Column(Integer, ForeignKey("users.id"), nullable=True)
    payment_reviewed_at    = Column(DateTime, nullable=True)

    admin_reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    admin_reviewed_at = Column(DateTime, nullable=True)

    published_at = Column(DateTime, nullable=True)
    expires_at   = Column(DateTime, nullable=True)
    sold_at      = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    seller  = relationship("User",    foreign_keys=[seller_id])
    booklet = relationship("Booklet")
    project = relationship("Project")
    purchase_requests = relationship("MarketplacePurchaseRequest", back_populates="listing",
                                      order_by="MarketplacePurchaseRequest.created_at.desc()",
                                      cascade="all, delete-orphan")

    def to_dict(self, include_private=False):
        d = {
            "id": self.id, "code": self.code, "slug": self.slug,
            "seller_id": self.seller_id, "seller_name": self.seller.full_name if self.seller else "",
            "booklet_id": self.booklet_id,
            "booklet_code": self.booklet.code if self.booklet else "",
            "project_id": self.project_id, "project_name": self.project.name if self.project else "",
            "title": self.title, "unit_type": self.unit_type, "area": self.area,
            "price": self.price, "negotiable": self.negotiable,
            "sale_terms": self.sale_terms, "description": self.description,
            "contact_method": self.contact_method,
            "status": self.status, "reject_reason": self.reject_reason,
            "fee_required": self.fee_required, "fee_amount": self.fee_amount,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "expires_at":   self.expires_at.isoformat()   if self.expires_at   else None,
            "sold_at":      self.sold_at.isoformat()      if self.sold_at      else None,
            "created_at":   self.created_at.isoformat(),
            "updated_at":   self.updated_at.isoformat(),
            "request_count": len(self.purchase_requests) if self.purchase_requests is not None else 0,
        }
        # شماره تماس فقط اگر فروشنده اجازه داده باشد نمایش عمومی پیدا کند
        if self.contact_method in (self.CONTACT_PHONE, self.CONTACT_BOTH):
            d["contact_phone"] = self.contact_phone
        if include_private:
            d.update({
                "payment_receipt_path": self.payment_receipt_path,
                "payment_date": self.payment_date,
                "payment_tracking_code": self.payment_tracking_code,
                "contact_phone": self.contact_phone,
            })
        return d


class MarketplacePurchaseRequest(Base):
    """درخواست تماس/خرید یک خریدار بالقوه برای یک آگهی بازار."""
    __tablename__ = "marketplace_purchase_requests"

    STATUS_NEW         = "new"
    STATUS_NEGOTIATING = "negotiating"
    STATUS_CONTACTED   = "contacted"
    STATUS_DEAL_DONE   = "deal_done"
    STATUS_CANCELLED   = "cancelled"

    id           = Column(Integer, primary_key=True)
    listing_id   = Column(Integer, ForeignKey("marketplace_listings.id", ondelete="CASCADE"), nullable=False)
    buyer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)   # اگر لاگین بوده
    buyer_name   = Column(String(120), nullable=False)
    buyer_phone  = Column(String(15),  nullable=False)
    message      = Column(Text)
    status       = Column(String(20), default=STATUS_NEW)
    ticket_id    = Column(Integer, ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    listing = relationship("MarketplaceListing", back_populates="purchase_requests")
    buyer   = relationship("User", foreign_keys=[buyer_user_id])
    ticket  = relationship("Ticket", foreign_keys=[ticket_id])

    def to_dict(self):
        return {
            "id": self.id, "listing_id": self.listing_id,
            "listing_code": self.listing.code if self.listing else "",
            "listing_title": self.listing.title if self.listing else "",
            "buyer_name": self.buyer_name, "buyer_phone": self.buyer_phone,
            "message": self.message, "status": self.status,
            "ticket_id": self.ticket_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
