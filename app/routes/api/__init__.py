"""API blueprints — همه ماژول‌های API را یکجا ثبت می‌کند."""
from flask import Blueprint

# ── Blueprint اصلی که به تمام sub-blueprint ها prefix می‌دهد ──────────────────
# این blueprint در app/__init__.py با url_prefix='/api' ثبت می‌شود.

from .projects      import bp as projects_bp
from .members       import bp as members_bp
from .booklets      import bp as booklets_bp
from .finance       import bp as finance_bp
from .announcements import bp as announcements_bp
from .transfers     import bp as transfers_bp
from .tickets       import bp as tickets_bp
from .notifications import bp as notifications_bp
from .settings      import bp as settings_bp
from .reports       import bp as reports_bp
from .bale          import bp as bale_bp
from .activity      import bp as activity_bp
from .profile       import bp as profile_bp
from .accounting    import bp as accounting_bp
from .overview       import bp as overview_bp
from .marketplace    import bp as marketplace_bp

all_blueprints = [
    projects_bp,
    members_bp,
    booklets_bp,
    finance_bp,
    announcements_bp,
    transfers_bp,
    tickets_bp,
    notifications_bp,
    settings_bp,
    reports_bp,
    bale_bp,
    activity_bp,
    profile_bp,
    accounting_bp,
    overview_bp,
    marketplace_bp,
]
