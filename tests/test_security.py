"""Hardening regression guards: account lockout, upload magic-byte checks,
DOCX decompression-bomb guard, LLM prompt-input caps, and the production
SECRET_KEY placeholder rejection."""
import io
import zipfile

import pytest


def _make_user(db_session, email="lock@example.com", password="Str0ng-Pass-9x"):
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
        data={"email": email, "password": "Str0ng-Pass-9x"},
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

    resp = client.post("/login", data={"email": email, "password": "Str0ng-Pass-9x"})
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]

    db_session.expire_all()
    user = db_session.get(User, uid)
    assert user.failed_login_count == 0
    assert user.locked_until is None


def test_lockout_escalates_and_keeps_counter(db_session):
    """Crossing the threshold again must lengthen the window, and the counter
    must NOT reset — otherwise waiting out one window buys a fresh batch of
    guesses forever."""
    from types import SimpleNamespace

    from app.security import LOCKOUT_THRESHOLD, register_failed_login

    u = SimpleNamespace(failed_login_count=0, locked_until=None)
    for _ in range(LOCKOUT_THRESHOLD):
        register_failed_login(u)
    first_lock = u.locked_until
    assert first_lock is not None
    assert u.failed_login_count == LOCKOUT_THRESHOLD  # not zeroed

    register_failed_login(u)  # one more failure
    assert u.failed_login_count == LOCKOUT_THRESHOLD + 1
    assert u.locked_until > first_lock  # escalated to a longer window


def test_missing_account_login_runs_dummy_hash(monkeypatch):
    """A login for a non-existent email must still spend hashing time so the
    response can't be timed to enumerate registered addresses."""
    import app.security as security

    called = {"n": 0}
    real = security.check_password_hash
    monkeypatch.setattr(
        security, "check_password_hash",
        lambda h, p: called.__setitem__("n", called["n"] + 1) or real(h, p),
    )
    security.dummy_password_check("whatever")
    assert called["n"] == 1


# ── Password policy ───────────────────────────────────────────────────────────


def test_password_policy_rejects_common_and_email_derived():
    from app.security import password_rejection_reason

    assert password_rejection_reason("password123", "a@b.com")   # common
    assert password_rejection_reason("aaaaaaaa", "a@b.com")      # low variety
    assert password_rejection_reason("jordanZ9x", "jordan@example.com")  # email in pw
    assert password_rejection_reason("Str0ng&Varied!", "a@b.com") is None


def test_signup_rejects_common_password(client, db_session):
    from app.models import User

    resp = client.post(
        "/sign-in",
        data={
            "email": "weakpw@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=True,
    )
    assert "too common" in resp.get_data(as_text=True)
    assert db_session.query(User).filter(User.email == "weakpw@example.com").one_or_none() is None


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


def test_docx_xml_entity_declaration_rejected(app):
    """A DOCX whose XML declares a DTD/entity (billion-laughs / XXE) must be
    rejected before python-docx/lxml parses it."""
    from app.resumes import ResumeError, extract_text

    buf = io.BytesIO()
    payload = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        b"<doc>&lol;</doc>"
    )
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", payload)
    with pytest.raises(ResumeError, match="disallowed XML"):
        extract_text(buf.getvalue(), "docx")


# ── LLM structured-output validation ──────────────────────────────────────────


def test_sanitize_structured_coerces_and_bounds():
    from app.resumes import _sanitize_structured

    dirty = {
        "name": 123,  # wrong type
        "summary": "ok",
        "experience": [
            {"company": "C", "title": "T", "dates": "D", "bullets": ["b1", 5, "b2"]},
            "not-a-dict",
        ],
        "evil_key": "should be dropped",
        "competencies": [{"label": "L", "items": "I"}],
        "education": [{"degree": "Deg", "school": "Sch"}],
        "tools": "x",
    }
    clean = _sanitize_structured(dirty)
    assert set(clean.keys()) == {
        "name", "contact_line_1", "contact_line_2", "summary",
        "experience", "competencies", "education", "tools",
    }
    assert clean["name"] == ""           # non-str coerced
    assert len(clean["experience"]) == 1  # non-dict entry dropped
    assert clean["experience"][0]["bullets"] == ["b1", "b2"]  # non-str bullet dropped


# ── Resume-credit atomic spend ────────────────────────────────────────────────


def test_resume_credit_consume_respects_cap(app, db_session):
    from app.models import Subscription, User
    from app.payments import consume_resume_credit

    user = _make_user(db_session, email="credits@example.com")
    sub = Subscription(user_id=user.id, city_limit=3)  # free = 10 lifetime
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)

    granted = sum(1 for _ in range(15) if consume_resume_credit(sub, 3))
    assert granted == 10  # never exceeds the free lifetime cap
    db_session.expire_all()
    assert db_session.get(Subscription, sub.id).resume_credits_used == 10


# ── LLM prompt-input caps ─────────────────────────────────────────────────────


def test_prompt_caps_exist_and_are_sane():
    from app.resumes import MAX_BASE_RESUME_CHARS, MAX_JOB_DESC_CHARS, RESUME_PROMPT

    assert 0 < MAX_JOB_DESC_CHARS <= 20_000
    assert 0 < MAX_BASE_RESUME_CHARS <= 50_000
    # The injection guard must stay in the prompt.
    assert "untrusted" in RESUME_PROMPT


# ── LLM cost abuse guard (OWASP LLM10) ────────────────────────────────────────


def test_interview_plan_post_is_rate_limited(app):
    """Fix #12: /interview/<job_id> POST triggers a paid Anthropic call, is_pro()
    is open to everyone, and no credit is spent — so the endpoint must carry an
    explicit rate limit (not just the loose global default) to cap LLM spend.
    Guards the interview LLM path exactly like the tailored-resume path."""
    from app import limiter

    decorated = limiter.limit_manager._decorated_limits
    key = "app.routes.interview_plan.interview_plan"
    assert key in decorated, "interview_plan lost its explicit rate limit"

    limits = [lim for group in decorated[key] for lim in group]
    assert limits, "interview_plan has no decorated limit"
    # The generate POST is what costs money; it must be capped to 30/hour and
    # scoped to POST so viewing a cached plan (GET) stays unthrottled.
    lim = limits[0]
    assert str(lim.limit) == "30 per 1 hour"
    assert lim.methods == ("post",)


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
