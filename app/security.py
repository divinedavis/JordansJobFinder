import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import requests
from flask import current_app

logger = logging.getLogger(__name__)


def generate_magic_token() -> Tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=current_app.config["MAGIC_LINK_TTL_MINUTES"]
    )
    return raw, token_hash, expires_at


def hash_magic_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# Account lockout: after this many consecutive failed logins, sign-in is
# rejected for the cooldown window — even with the right password — so
# distributed/slow brute force can't grind a single account indefinitely.
LOCKOUT_THRESHOLD = 10
LOCKOUT_MINUTES = 15


def _naive_utc_now() -> datetime:
    """SQLite stores naive datetimes — compare lockout times like-for-like."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def account_locked(user) -> bool:
    """True while the user's lockout window is still running."""
    return user.locked_until is not None and user.locked_until > _naive_utc_now()


def register_failed_login(user) -> None:
    """Count a failed attempt; start the lockout window at the threshold.
    Caller commits."""
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= LOCKOUT_THRESHOLD:
        user.locked_until = _naive_utc_now() + timedelta(minutes=LOCKOUT_MINUTES)
        user.failed_login_count = 0


def clear_failed_logins(user) -> None:
    """Successful sign-in resets the brute-force counters. Caller commits."""
    user.failed_login_count = 0
    user.locked_until = None


def hash_identifier(value: str) -> str:
    """Short stable hash for logging identifiers (emails) without writing PII."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def verify_turnstile(token: str, remote_ip: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    secret = current_app.config.get("TURNSTILE_SECRET_KEY", "")
    if not secret:
        logger.warning(
            "TURNSTILE_SECRET_KEY is not configured — bot protection is disabled. "
            "Set the key in .env to enforce Turnstile verification."
        )
        return False, "Bot protection is not configured."

    if not token:
        # No token in the request — never round-trip an empty value to
        # Cloudflare (it would 'fail' anyway); reject explicitly.
        return False, "Bot protection check did not pass."

    try:
        response = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": secret,
                "response": token,
                "remoteip": remote_ip,
            },
            timeout=10,
        )
        payload = response.json()
    except Exception:
        return False, "Bot protection verification failed."

    if payload.get("success"):
        return True, None
    return False, "Bot protection check did not pass."


def enforce_turnstile(token: str, remote_ip: Optional[str] = None) -> Optional[str]:
    """Fail-closed Turnstile gate for the auth routes.

    Returns ``None`` when the request may proceed, or an error string when it
    must be rejected. Bot protection is enforced whenever a secret is
    configured OR when the app declares Turnstile required (production). In
    that mode a missing/invalid token — or even a missing secret, which is a
    production misconfiguration — rejects the request instead of passing it.
    Only when Turnstile is neither configured nor required (local dev, tests)
    is the check skipped so the request proceeds.
    """
    configured = bool(current_app.config.get("TURNSTILE_SECRET_KEY"))
    required = bool(current_app.config.get("TURNSTILE_REQUIRED"))

    if not configured and not required:
        return None

    ok, err = verify_turnstile(token, remote_ip)
    if ok:
        return None
    return err or "Bot verification failed."
