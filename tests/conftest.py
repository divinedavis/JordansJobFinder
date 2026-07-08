"""Test fixtures.

Env vars must be set at *module load* (not inside a fixture) because
pytest's collection imports test modules, which import `app.*`, which
evaluates `Config` at class-definition time and reads SECRET_KEY from env.
"""
import os
import tempfile
from pathlib import Path

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="jjf-test-db-"))
_TEST_RESUME_DIR = Path(tempfile.mkdtemp(prefix="jjf-test-resumes-"))
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR / 'test.db'}"
os.environ["RESUME_UPLOAD_DIR"] = str(_TEST_RESUME_DIR / "base")
os.environ["RESUME_TAILORED_DIR"] = str(_TEST_RESUME_DIR / "tailored")
os.environ.setdefault("SUPERUSER_EMAIL", "superuser@example.com")
for _key in (
    "TURNSTILE_SECRET_KEY",
    "TURNSTILE_SITE_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
):
    os.environ.pop(_key, None)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app():
    # Reload catalog so SUPERUSER_EMAIL picks up the env var set above.
    from app import catalog as _catalog
    _catalog.SUPERUSER_EMAIL = os.environ["SUPERUSER_EMAIL"].strip().lower()

    from app import create_app, limiter
    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        RATELIMIT_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
    )
    # The config flag alone doesn't disable an already-initialized limiter;
    # flip the instance attribute so the per-view limits are skipped.
    limiter.enabled = False
    return flask_app


@pytest.fixture(autouse=True)
def _reset_db(app):
    """Drop + recreate all tables before each test so state is isolated."""
    from app.db import Base, engine, close_db_session
    import app.models  # noqa: F401  ensure models are registered

    close_db_session()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    close_db_session()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    from app.db import get_db
    return get_db()


def _signup(client, email="user@example.com", password="Str0ng-Pass-9x"):
    return client.post(
        "/sign-in",
        data={
            "email": email,
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=False,
    )


@pytest.fixture
def signed_in_client(client):
    response = _signup(client)
    assert response.status_code == 302, response.data
    return client


@pytest.fixture
def superuser_client(client):
    response = _signup(client, email=os.environ["SUPERUSER_EMAIL"])
    assert response.status_code == 302, response.data
    return client
