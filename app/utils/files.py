"""مدیریت آپلود فایل — بررسی MIME/محتوا و ذخیره‌سازی ایمن"""
import os
import random
from flask import current_app
from werkzeug.utils import secure_filename

from ..constants import (
    ALLOWED_IMAGE_MIMES, ALLOWED_VIDEO_MIMES, ALLOWED_DOC_MIMES,
    MAX_IMAGE_BYTES, MAX_VIDEO_BYTES, MAX_DOC_BYTES,
    MIME_TO_EXT, MAGIC_BYTES,
)


class FileValidationError(ValueError):
    """خطای اعتبارسنجی فایل آپلودی"""


def save_upload(file, subfolder: str, ext: str) -> str:
    """
    فایل آپلودی را با نام تصادفی و پسوند تعیین‌شده توسط سرور (نه کاربر) ذخیره
    می‌کند و مسیر نسبی آن را برمی‌گرداند.

    مهم: پسوند فایل هرگز از نام اصلی فایل کاربر گرفته نمی‌شود — وگرنه یک فایل
    HTML/SVG حاوی اسکریپت را می‌شد با Content-Type جعلی «image/jpeg» رد کرد و
    با پسوند .html ذخیره کرد؛ چون /uploads/ فایل را با Content-Type برگرفته از
    پسوند سرو می‌کند (نه از محتوا)، این یعنی XSS ذخیره‌شده روی همان دامنه پنل.

    Args:
        file: FileStorage از Flask
        subfolder: زیرپوشه داخل UPLOAD_FOLDER (مثال: 'projects')
        ext: پسوند امن (نقطه‌دار) که از روی MIME تأییدشده تعیین شده — نه از نام فایل کاربر

    Returns:
        مسیر نسبی فایل ذخیره‌شده، مثال: 'projects/123456_name.jpg'
    """
    if not file or not file.filename:
        raise FileValidationError("فایلی ارسال نشده.")

    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(folder, exist_ok=True)

    prefix    = random.randint(10**5, 10**6 - 1)
    base_name = secure_filename(os.path.splitext(file.filename)[0]) or "file"
    filename  = f"{prefix}_{base_name}{ext}"
    file.save(os.path.join(folder, filename))
    return f"{subfolder}/{filename}"


def save_image(file, subfolder: str) -> str:
    """آپلود تصویر با بررسی MIME، محتوای واقعی فایل و حجم."""
    ext = _validate_mime(file, ALLOWED_IMAGE_MIMES, MAX_IMAGE_BYTES)
    return save_upload(file, subfolder, ext)


def save_video(file, subfolder: str) -> str:
    """آپلود ویدیو با بررسی MIME و حجم."""
    ext = _validate_mime(file, ALLOWED_VIDEO_MIMES, MAX_VIDEO_BYTES)
    return save_upload(file, subfolder, ext)


def save_document(file, subfolder: str) -> str:
    """آپلود سند (تصویر یا PDF) با بررسی MIME، محتوای واقعی فایل و حجم."""
    ext = _validate_mime(file, ALLOWED_DOC_MIMES, MAX_DOC_BYTES)
    return save_upload(file, subfolder, ext)


def detect_media_type(file) -> str:
    """نوع رسانه فایل را برمی‌گرداند: 'video' یا 'image'."""
    mime = (file.content_type or "").lower()
    return "video" if mime.startswith("video/") else "image"


def _validate_mime(file, allowed_mimes: set, max_bytes: int) -> str:
    """MIME اعلام‌شده، امضای بایت آغازین و حجم فایل را بررسی می‌کند و پسوند امن برمی‌گرداند."""
    mime = (file.content_type or "").lower()
    if mime not in allowed_mimes:
        raise FileValidationError(
            f"نوع فایل مجاز نیست. انواع پشتیبانی‌شده: {', '.join(sorted(allowed_mimes))}"
        )

    file.stream.seek(0)
    head = file.stream.read(16)
    file.stream.seek(0)

    signatures = MAGIC_BYTES.get(mime)
    if signatures:
        if mime == "image/webp":
            ok = head.startswith(b"RIFF") and head[8:12] == b"WEBP"
        else:
            ok = any(head.startswith(sig) for sig in signatures)
        if not ok:
            raise FileValidationError(
                "محتوای فایل با نوع اعلام‌شده مطابقت ندارد — فایل واقعاً از نوع مجاز نیست."
            )

    # بررسی حجم (stream هنوز باز است)
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise FileValidationError(f"حجم فایل نباید از {mb} مگابایت بیشتر باشد.")

    return MIME_TO_EXT.get(mime, "")
