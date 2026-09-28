"""ثابت‌های دامنه — جلوگیری از Magic String در سراسر پروژه"""


class Role:
    ADMIN   = "admin"
    MEMBER  = "member"
    FINANCE = "finance"   # مسئول مالی — دسترسی فقط به بخش مالی/حسابداری


class ExpenseCategory:
    LAND       = "land"        # خرید زمین
    CONTRACTOR = "contractor"  # پیمانکار
    ADMIN      = "admin"       # اداری
    UTILITY    = "utility"     # خدمات/تأسیسات
    OTHER      = "other"


class BookletShareType:
    FULL = "full"
    HALF = "half"


class PaymentStatus:
    UNPAID  = "unpaid"
    PAID    = "paid"
    OVERDUE = "overdue"


class TransferStatus:
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TicketStatus:
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    WAITING     = "waiting"
    RESOLVED    = "resolved"
    CLOSED      = "closed"


class TicketPriority:
    LOW    = "low"
    NORMAL = "normal"
    HIGH   = "high"


class ProjectStatus:
    ACTIVE    = "active"
    COMPLETED = "completed"
    UPCOMING  = "upcoming"


class NotificationType:
    INFO    = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR   = "error"


class LogCategory:
    GENERAL  = "general"
    ADMIN    = "admin"
    MEMBER   = "member"
    FINANCE  = "finance"
    TRANSFER = "transfer"
    TICKET   = "ticket"
    BOOKLET  = "booklet"


# رمز عبور پیش‌فرض برای مالکان جدید ایجادشده از طریق انتقال
# این مقدار را از طریق env var بارگذاری کنید در محیط production
DEFAULT_NEW_OWNER_PASSWORD = "changeme123"

# محدودیت‌های آپلود
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO_MIMES = {"video/mp4", "video/webm", "video/ogg"}
ALLOWED_DOC_MIMES   = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
}

# پسوند فایل ذخیره‌شده همیشه از روی MIME تأییدشده تعیین می‌شود، نه از روی نام
# فایل کاربر — تا کسی نتواند با یک Content-Type جعلی (مثلاً image/jpeg روی یک
# فایل .html حاوی اسکریپت) پسوند اجرایی/HTML را از دروازه رد کند (Stored XSS).
MIME_TO_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/ogg": ".ogv",
    "application/pdf": ".pdf",
}

# امضای بایت آغازین فایل‌های واقعی — برای رد فایل‌هایی که Content-Type درست
# اعلام کرده‌اند اما محتوایشان با آن نوع مطابقت ندارد (مثلاً HTML با ادعای jpeg)
MAGIC_BYTES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png":  (b"\x89PNG\r\n\x1a\n",),
    "image/gif":  (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),   # بایت‌های ۸ تا ۱۲ باید WEBP باشد — جداگانه بررسی می‌شود
    "application/pdf": (b"%PDF-",),
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_VIDEO_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_DOC_BYTES   = 20 * 1024 * 1024   # 20 MB
