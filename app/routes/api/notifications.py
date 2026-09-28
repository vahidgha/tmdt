"""API ماژول اعلان‌ها"""
from flask import Blueprint, jsonify
from flask_login import current_user, login_required
from sqlalchemy import func

from ... import db_session
from ...models import Notification, User
from ...utils.http import get_request_body, log_activity, require_admin

bp = Blueprint("notifications", __name__)


@bp.get("/notifications")
@login_required
def notifications_list():
    items = (db_session.query(Notification)
             .filter_by(user_id=current_user.id)
             .order_by(Notification.created_at.desc())
             .limit(50)
             .all())
    return jsonify(
        notifications=[{
            "id": n.id, "title": n.title, "body": n.body,
            "type": n.type, "read": n.read,
            "created_at": n.created_at.isoformat(),
        } for n in items],
        unread_count=sum(1 for n in items if not n.read),
    )


@bp.get("/notifications/unread-count")
@login_required
def notifications_unread_count():
    """
    فقط شمارش — برای بج اعلان که هر ۳۰ ثانیه در همه صفحات پنل poll می‌شود.
    قبلاً کل لیست ۵۰تایی اعلان‌ها serialize می‌شد فقط برای شمردن unread؛
    این مسیر سبک با یک COUNT(*) جایگزینش می‌کند.
    """
    count = (db_session.query(func.count(Notification.id))
             .filter_by(user_id=current_user.id, read=False).scalar())
    return jsonify(unread_count=count)


@bp.post("/notifications/read")
@login_required
def notifications_read():
    ids = get_request_body().get("ids")
    q   = db_session.query(Notification).filter_by(user_id=current_user.id, read=False)
    if ids:
        q = q.filter(Notification.id.in_(ids))
    q.update({"read": True}, synchronize_session=False)
    db_session.commit()
    return jsonify(ok=True)


@bp.post("/notifications/send")
@login_required
def notifications_send():
    err = require_admin()
    if err: return err

    data = get_request_body()
    uid  = data.get("user_id")
    if uid:
        targets = db_session.query(User).filter_by(id=int(uid)).all()
    else:
        targets = db_session.query(User).filter_by(role="member", active=True).all()

    for m in targets:
        db_session.add(Notification(
            user_id=m.id,
            title=data.get("title", ""),
            body=data.get("body", ""),
            type=data.get("type", "info"),
        ))
    db_session.commit()
    log_activity("notification_send",
                 f"اعلان ارسال شد به {len(targets)} کاربر: {data.get('title', '')}",
                 "admin")
    return jsonify(ok=True, sent=len(targets)), 201
