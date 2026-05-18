import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _require_secret_key() -> str:
    """Return SECRET_KEY from the environment.

    Fail hard if it is unset so production never falls back to a publicly
    known key (which would allow forging signed session cookies). Set
    ALLOW_DEV_SECRET=1 for local development to permit the dev fallback.
    """
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    if os.getenv("ALLOW_DEV_SECRET") == "1":
        return "dev-secret-key"
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. Set it in production, "
        "or set ALLOW_DEV_SECRET=1 for local development."
    )


class Config:
    SECRET_KEY = _require_secret_key()
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
    MAGIC_LINK_TTL_MINUTES = 20
    FREE_CITIES = ("New York, NY", "Atlanta, GA", "Miami, FL")
    FREE_SEARCH_CHANGE_LIMIT = 2
    PAID_CITY_LIMIT = 3
