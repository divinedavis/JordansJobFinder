import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ["SECRET_KEY"]
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
    TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
    TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
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
    PERMANENT_SESSION_LIFETIME = 86400 * 30  # 30 days
