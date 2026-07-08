import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import requests
from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)


# Precomputed hash of a throwaway password. When a login is attempted for an
# email that doesn't exist, we still run a password check against this so the
# response takes the same time as a real account — otherwise the early return
# (no hashing) makes non-existent emails answer far faster, leaking which
# addresses are registered (user enumeration). Generated with the same default
# method User.set_password uses, so the cost matches.
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))


def dummy_password_check(password: str) -> None:
    """Burn the same time a real password verification costs. Result ignored."""
    check_password_hash(_DUMMY_PASSWORD_HASH, password or "")


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
# Escalating lockout is capped here so an account can always recover.
LOCKOUT_MAX_MINUTES = 24 * 60


def _naive_utc_now() -> datetime:
    """SQLite stores naive datetimes — compare lockout times like-for-like."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def account_locked(user) -> bool:
    """True while the user's lockout window is still running."""
    return user.locked_until is not None and user.locked_until > _naive_utc_now()


def register_failed_login(user) -> None:
    """Count a failed attempt; open an escalating lockout window at the
    threshold. Caller commits.

    The counter is deliberately NOT reset when a window opens: each additional
    failure at or past the threshold doubles the cooldown (15m, 30m, 60m, …),
    capped at LOCKOUT_MAX_MINUTES. Resetting it — as the old code did — let an
    attacker wait out one 15-minute window and get a fresh batch of 10 guesses
    forever; keeping the count means they're re-locked immediately, and longer,
    until a successful sign-in clears it via clear_failed_logins()."""
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= LOCKOUT_THRESHOLD:
        over = user.failed_login_count - LOCKOUT_THRESHOLD
        minutes = min(LOCKOUT_MINUTES * (2 ** over), LOCKOUT_MAX_MINUTES)
        user.locked_until = _naive_utc_now() + timedelta(minutes=minutes)


def clear_failed_logins(user) -> None:
    """Successful sign-in resets the brute-force counters. Caller commits."""
    user.failed_login_count = 0
    user.locked_until = None


# A small offline blocklist of the passwords that dominate credential-stuffing
# lists. Not exhaustive — a defense-in-depth floor so the most-guessed strings
# can't protect an account. (A full HIBP k-anonymity check can layer on later.)
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "12345678", "123456789",
    "1234567890", "qwertyuiop", "qwerty123", "111111111", "iloveyou", "admin123",
    "letmein123", "welcome1", "welcome123", "abc12345", "monkey123", "dragon123",
    "sunshine1", "princess1", "football1", "baseball1", "trustno1", "changeme1",
    "starwars1", "whatever1", "superman1", "michael1", "jordan123",
}


def password_rejection_reason(password: str, email: str = "") -> Optional[str]:
    """Return a user-facing reason to reject a chosen password, or None if it's
    acceptable. Enforced at signup so weak/guessable passwords never take.

    Length bounds are still checked by the route; this adds a common-password
    blocklist, an email-derived-password check, and a minimal-variety floor."""
    if not password:
        return "Password is required."
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS:
        return "That password is too common. Please choose a less predictable one."
    local = (email or "").split("@", 1)[0].strip().lower()
    if local and len(local) >= 3 and local in lowered:
        return "Password must not contain your email address."
    if len(set(password)) < 5:
        return "Password isn't varied enough — use a longer mix of characters."
    return None


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
