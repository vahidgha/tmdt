import os, tempfile
import pytest
from app import create_app
from app.extensions import limiter


@pytest.fixture(scope="session")
def app():
    """Shared Flask app for all test modules."""
    os.environ["DATABASE_URL"] = "sqlite://"
    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        UPLOAD_FOLDER=tempfile.mkdtemp(),
        SERVER_NAME="localhost",
        WTF_CSRF_ENABLED=False,   # CSRF در تست‌ها غیرفعال — جدا تست می‌شود
        RATELIMIT_ENABLED=False,  # rate limit در تست‌ها غیرفعال
    )
    limiter.enabled = False
    yield flask_app
