"""Hardening regression guards: account lockout, upload magic-byte checks,
DOCX decompression-bomb guard, LLM prompt-input caps, and the production
SECRET_KEY placeholder rejection."""
import io
import zipfile

import pytest


def _make_user(db_session, email="lock@example.com", password="password123"):
    from app.models import User

    user = User(email=email)
    user.set_password(password)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ── Login lockout ─────────────────────────────────────────────────────────────


def test_lockout_after_repeated_failed_logins(client, db_session):
    from app.models import User
    from app.security import LOCKOUT_THRESHOLD

    user = _make_user(db_session)
    email, uid = user.email, user.id
    for _ in range(LOCKOUT_THRESHOLD):
        resp = client.post("/login", data={"email": email, "password": "wrong-pass"})
        assert resp.status_code == 302

    db_session.expire_all()
    assert db_session.get(User, uid).locked_until is not None, (
        "lockout window never started"
    )

    # Even the CORRECT password is rejected while the window runs.
    resp = client.post(
        "/login",
        data={"email": email, "password": "password123"},
        follow_redirects=True,
    )
    assert "Too many failed attempts" in resp.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_lockout_expires_and_success_resets_counters(client, db_session):
    from datetime import datetime, timedelta

    from app.models import User

    user = _make_user(db_session, email="lock2@example.com")
    email, uid = user.email, user.id
    user.failed_login_count = 3
    user.locked_until = datetime.utcnow() - timedelta(minutes=1)  # already over
    db_session.commit()

    resp = client.post("/login", data={"email": email, "password": "password123"})
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]

    db_session.expire_all()
    user = db_session.get(User, uid)
    assert user.failed_login_count == 0
    assert user.locked_until is None


# ── Upload content validation ─────────────────────────────────────────────────


def test_pdf_extraction_requires_pdf_magic_bytes(app):
    from app.resumes import ResumeError, extract_text

    with pytest.raises(ResumeError):
        extract_text(b"<html>not a pdf</html>", "pdf")


def test_docx_extraction_requires_zip_magic_bytes(app):
    from app.resumes import ResumeError, extract_text

    with pytest.raises(ResumeError):
        extract_text(b"plain text pretending to be docx", "docx")


def test_docx_decompression_bomb_rejected(app):
    from app.resumes import MAX_DOCX_UNCOMPRESSED_BYTES, ResumeError, extract_text

    # A tiny zip whose single entry inflates past the cap.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "word/document.xml", b"\0" * (MAX_DOCX_UNCOMPRESSED_BYTES + 1)
        )
    with pytest.raises(ResumeError, match="expands too large"):
        extract_text(buf.getvalue(), "docx")


# ── LLM prompt-input caps ─────────────────────────────────────────────────────


def test_prompt_caps_exist_and_are_sane():
    from app.resumes import MAX_BASE_RESUME_CHARS, MAX_JOB_DESC_CHARS, RESUME_PROMPT

    assert 0 < MAX_JOB_DESC_CHARS <= 20_000
    assert 0 < MAX_BASE_RESUME_CHARS <= 50_000
    # The injection guard must stay in the prompt.
    assert "untrusted" in RESUME_PROMPT


# ── Production SECRET_KEY guard ───────────────────────────────────────────────


def test_production_rejects_placeholder_secret_key(monkeypatch):
    import importlib

    import app.config as config_module

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "change-me")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        importlib.reload(config_module)

    # Restore the test configuration for the rest of the suite.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    importlib.reload(config_module)
