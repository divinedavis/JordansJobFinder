"""Turnstile bot protection must fail CLOSED.

Regression guard for the fail-open hole: when Turnstile is configured (a
secret is set) or declared required (production), a missing/invalid token —
or a missing secret in production — must REJECT signup/login rather than
silently waving the request through.
"""
import app.security as security


def _signup_payload(email="botcheck@example.com", password="password123"):
    return {
        "email": email,
        "password": password,
        "confirm_password": password,
        # Note: no cf-turnstile-response — simulates a request with no token.
    }


def test_signup_rejected_when_secret_set_and_token_missing(client, app, monkeypatch):
    """Secret configured + no token => reject (don't create the account)."""
    from app.models import User
    from app.db import get_db

    monkeypatch.setitem(app.config, "TURNSTILE_SECRET_KEY", "test-secret")
    # Guard: verify_turnstile must not even reach Cloudflare for an empty token,
    # but if it ever did we force a hard failure so the test can't pass falsely.
    monkeypatch.setattr(
        security, "verify_turnstile", lambda *a, **k: (False, "blocked")
    )

    resp = client.post("/sign-in", data=_signup_payload())
    assert resp.status_code == 302
    assert "/sign-in" in resp.headers["Location"]

    with app.app_context():
        db = get_db()
        assert db.query(User).filter(
            User.email == "botcheck@example.com"
        ).one_or_none() is None


def test_signup_rejected_when_required_even_without_secret(client, app, monkeypatch):
    """Production intent (TURNSTILE_REQUIRED) + no secret => fail closed."""
    from app.models import User
    from app.db import get_db

    monkeypatch.setitem(app.config, "TURNSTILE_SECRET_KEY", "")
    monkeypatch.setitem(app.config, "TURNSTILE_REQUIRED", True)

    resp = client.post("/sign-in", data=_signup_payload(email="req@example.com"))
    assert resp.status_code == 302
    assert "/sign-in" in resp.headers["Location"]

    with app.app_context():
        db = get_db()
        assert db.query(User).filter(
            User.email == "req@example.com"
        ).one_or_none() is None


def test_login_rejected_when_secret_set_and_token_invalid(client, app, monkeypatch):
    """Secret configured + token present but invalid => reject login."""
    # Seed a real account WITHOUT Turnstile in the way.
    monkeypatch.setitem(app.config, "TURNSTILE_SECRET_KEY", "")
    monkeypatch.setitem(app.config, "TURNSTILE_REQUIRED", False)
    signup = client.post(
        "/sign-in",
        data={
            "email": "real@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    assert signup.status_code == 302
    with client.session_transaction() as sess:
        sess.clear()

    # Now turn Turnstile on and make verification fail.
    monkeypatch.setitem(app.config, "TURNSTILE_SECRET_KEY", "test-secret")
    monkeypatch.setattr(
        security, "verify_turnstile", lambda *a, **k: (False, "blocked")
    )

    resp = client.post(
        "/login",
        data={
            "email": "real@example.com",
            "password": "password123",
            "cf-turnstile-response": "tampered",
        },
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_signup_allowed_when_unconfigured_and_not_required(client, app, monkeypatch):
    """Local/dev default (no secret, not required) still lets signup through."""
    monkeypatch.setitem(app.config, "TURNSTILE_SECRET_KEY", "")
    monkeypatch.setitem(app.config, "TURNSTILE_REQUIRED", False)

    resp = client.post("/sign-in", data=_signup_payload(email="dev@example.com"))
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]
