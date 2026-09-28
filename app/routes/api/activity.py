"""API ماژول لاگ فعالیت‌ها"""
import math

from flask import Blueprint, jsonify, request
from flask_login import login_required
from sqlalchemy import func, or_

from ... import db_session
from ...models import ActivityLog
from ...utils.http import require_admin

bp = Blueprint("activity", __name__)


@bp.get("/activity-log")
@login_required
def activity_log_list():
    err = require_admin()
    if err: return err

    page      = int(request.args.get("page", 1))
    per_page  = int(request.args.get("per_page", 50))
    category  = request.args.get("category", "").strip()
    user_id   = request.args.get("user_id", "").strip()
    search    = request.args.get("search", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to   = request.args.get("date_to", "").strip()

    q = db_session.query(ActivityLog).order_by(ActivityLog.created_at.desc())
    if category:  q = q.filter(ActivityLog.category == category)
    if user_id:   q = q.filter(ActivityLog.user_id == int(user_id))
    if search:
        q = q.filter(or_(
            ActivityLog.action.contains(search),
            ActivityLog.detail.contains(search),
            ActivityLog.ip.contains(search),
        ))
    if date_from: q = q.filter(ActivityLog.created_at >= date_from)
    if date_to:   q = q.filter(ActivityLog.created_at <= date_to + " 23:59:59")

    total = q.count()
    logs  = q.offset((page - 1) * per_page).limit(per_page).all()

    stats = {
        action_val: cnt
        for action_val, cnt in db_session.query(
            ActivityLog.action, func.count(ActivityLog.id)
        ).group_by(ActivityLog.action).all()
    }
    stats["transfer"] = sum(v for k, v in stats.items() if k.startswith("transfer"))

    return jsonify(
        logs=[log.to_dict() for log in logs],
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page),
        stats=stats,
    )
