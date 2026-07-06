import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


_WEAK_SECRET_KEYS = {"change-me", "changeme", "secret", "dev", "development"}


class Config:
    SECRET_KEY = os.environ["SECRET_KEY"]
    # A guessable session-signing key lets anyone forge login cookies. Refuse
    # to boot production with the .env.example placeholder or a trivially
    # short key (dev/tests keep working with whatever they set).
    if os.getenv("APP_ENV", "development") == "production" and (
        SECRET_KEY.lower() in _WEAK_SECRET_KEYS or len(SECRET_KEY) < 16
    ):
        raise RuntimeError(
            "SECRET_KEY is a placeholder or too short for production — "
            "generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'jordansjobfinder.db'}",
    )
    BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_CITY_PLAN_PRICE_ID = os.getenv("STRIPE_CITY_PLAN_PRICE_ID", "")
    STRIPE_UNLOCK_PRICE_ID = os.getenv("STRIPE_UNLOCK_PRICE_ID", "")
    # City-tier subscriptions: 5 cities ($9.99/mo) and 10 cities ($19.99/mo).
    STRIPE_CITY5_PRICE_ID = os.getenv("STRIPE_CITY5_PRICE_ID", "")
    STRIPE_CITY10_PRICE_ID = os.getenv("STRIPE_CITY10_PRICE_ID", "")
    APP_ENV = os.getenv("APP_ENV", "development")
    TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
    TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
    # In production we *intend* Turnstile to be enforced. When required, the
    # auth routes fail CLOSED: a missing/invalid token — or a missing secret
    # (itself a misconfiguration) — rejects the request rather than waving it
    # through. Outside production (local dev, the test suite) Turnstile is only
    # enforced when a secret happens to be set.
    TURNSTILE_REQUIRED = APP_ENV == "production"
    MAGIC_LINK_TTL_MINUTES = 20
    FREE_CITIES = ("New York, NY", "Atlanta, GA", "Miami, FL")
    FREE_SEARCH_CHANGE_LIMIT = 2
    PAID_CITY_LIMIT = 3

    # Resume tailoring
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    RESUME_UPLOAD_DIR = os.getenv("RESUME_UPLOAD_DIR", str(BASE_DIR / "resumes" / "base"))
    RESUME_TAILORED_DIR = os.getenv("RESUME_TAILORED_DIR", str(BASE_DIR / "resumes" / "tailored"))
    RESUME_MAX_UPLOAD_BYTES = int(os.getenv("RESUME_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))  # 5 MB

    # Secure session cookies
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 86400 * 14  # 14 days

    # flask-limiter counter storage. The in-memory default is per-gunicorn-worker
    # (each worker keeps its own counts), so production points this at Redis via
    # .env; dev and the test suite stay on memory://.
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
