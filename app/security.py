import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import requests
from flask import current_app


def generate_magic_token() -> Tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=current_app.config["MAGIC_LINK_TTL_MINUTES"]
    )
    return raw, token_hash, expires_at


def hash_magic_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def verify_turnstile(token: str, remote_ip: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    secret = current_app.config["TURNSTILE_SECRET_KEY"]
    if not secret:
        return True, None

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
