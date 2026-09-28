"""API ماژول پروفایل کاربر"""
from flask import Blueprint, jsonify
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from ... import db_session
from ...utils.http import get_request_body, log_activity
from ...utils.validation import validate_user_fields

bp = Blueprint("profile", __name__)

_PROFILE_FIELDS = [
    "first_name", "last_name", "father_name", "birth_date", "birth_place",
    "marital_status", "phone", "emergency_phone", "landline", "address",
    "postal_code", "occupation", "email", "bank_name", "account_number", "iban",
]


@bp.get("/profile/me")
@login_required
def profile_me():
    d             = current_user.to_dict()
    d["booklets"] = [b.to_dict() for b in current_user.booklets]
    return jsonify(**d, user=current_user.to_dict())


@bp.post("/profile/complete")
@login_required
def profile_complete():
    data = get_request_body()
    v_err = validate_user_fields(data)
    if v_err:
        return jsonify(error=v_err), 400
    for field in _PROFILE_FIELDS:
        if field in data:
            setattr(current_user, field, data[field])

    if current_user.missing_profile_fields():
        return jsonify(error="لطفاً همه فیلدهای الزامی (*) را تکمیل کنید."), 400

    # تنظیم رمز عبور بدون تأیید رمز فعلی فقط در همین تکمیل اولیهٔ پروفایل
    # (پیش از این‌که profile_complete=True شود) مجاز است — بعد از آن، تغییر
    # رمز فقط باید از /profile/change-password (با تأیید رمز فعلی) ممکن باشد،
    # وگرنه این مسیر می‌شد راهی برای عبور از آن بررسی.
    if data.get("new_password") and not current_user.profile_complete:
        if data["new_password"] != data.get("confirm_password", ""):
            return jsonify(error="رمزهای عبور مطابقت ندارند."), 400
        if len(data["new_password"]) < 6:
            return jsonify(error="رمز عبور باید حداقل ۶ کاراکتر باشد."), 400
        current_user.password_hash = generate_password_hash(data["new_password"])

    current_user.profile_complete = True
    db_session.commit()
    return jsonify(ok=True)


@bp.post("/profile/change-password")
@login_required
def change_password():
    """تغییر رمز عبور توسط خود کاربر — با تأیید رمز فعلی."""
    data        = get_request_body()
    current_pw  = data.get("current_password", "")
    new_pw      = data.get("new_password", "")
    confirm_pw  = data.get("confirm_password", "")

    if not check_password_hash(current_user.password_hash, current_pw):
        return jsonify(error="رمز عبور فعلی اشتباه است."), 400
    if len(new_pw) < 6:
        return jsonify(error="رمز عبور جدید باید حداقل ۶ کاراکتر باشد."), 400
    if new_pw != confirm_pw:
        return jsonify(error="رمز عبور جدید و تکرار آن مطابقت ندارند."), 400
    if check_password_hash(current_user.password_hash, new_pw):
        return jsonify(error="رمز عبور جدید نباید با رمز فعلی یکسان باشد."), 400

    current_user.password_hash = generate_password_hash(new_pw)
    db_session.commit()
    log_activity("password_change", "تغییر رمز عبور توسط کاربر", "auth")
    return jsonify(ok=True)
