"""AI interview prep (Pro-only feature): plan sanitization, the Pro gate,
storage/caching, and the dashboard upsell button."""


def _make_pro(db_session, email="user@example.com"):
    from app.models import Subscription, User

    user = db_session.query(User).filter(User.email == email).one()
    sub = db_session.query(Subscription).filter(Subscription.user_id == user.id).one_or_none()
    if sub is None:
        sub = Subscription(user_id=user.id)
        db_session.add(sub)
    sub.city_limit = 10
    db_session.commit()
    return user


def _seed_job(db_session):
    from app.models import Job

    job = Job(
        source="test", company="Boeing", title="Supply Chain Manager",
        normalized_title="supply chain manager",
        url="https://example.com/jobs/iv-1", city="charleston-sc",
        location="North Charleston, SC", description="Lead procurement.",
        vertical="scm", is_technical=False,
    )
    db_session.add(job)
    db_session.commit()
    return job


# ── Plan sanitization ─────────────────────────────────────────────────────────


def test_sanitize_plan_coerces_and_bounds():
    from app.interview import sanitize_plan

    dirty = {
        "role_summary": 123,  # wrong type
        "question_groups": [
            {"category": "Behavioral", "questions": ["q1", 5, "q2"]},
            "not-a-dict",
        ],
        "schedule": [
            {"day": 1, "minutes": "45", "focus": "Study"},
            {"day": "x", "minutes": 99999, "focus": 7},
        ],
        "day_of_tips": ["tip1", None, "tip2"],
        "evil_key": "dropped",
    }
    clean = sanitize_plan(dirty)
    assert set(clean.keys()) == {"role_summary", "question_groups", "schedule", "day_of_tips"}
    assert clean["role_summary"] == ""  # non-str coerced
    assert clean["question_groups"][0]["questions"] == ["q1", "q2"]  # non-str dropped
    assert len(clean["question_groups"]) == 1  # non-dict dropped
    assert clean["schedule"][0]["minutes"] == 45  # numeric string coerced
    assert clean["schedule"][1]["minutes"] == 600  # bounded
    assert clean["day_of_tips"] == ["tip1", "tip2"]


# ── Pro gate ──────────────────────────────────────────────────────────────────


def test_free_user_cannot_generate_plan(signed_in_client, db_session):
    from app.models import InterviewPlan

    job_id = _seed_job(db_session).id
    resp = signed_in_client.post(f"/interview/{job_id}", follow_redirects=False)
    assert resp.status_code == 302
    assert "/billing" in resp.headers["Location"]
    assert db_session.query(InterviewPlan).count() == 0


def test_free_user_sees_upgrade_cta(signed_in_client, db_session):
    job_id = _seed_job(db_session).id
    body = signed_in_client.get(f"/interview/{job_id}").get_data(as_text=True)
    assert "Pro" in body
    assert "Upgrade to Pro" in body


def test_pro_user_generates_and_caches_plan(signed_in_client, db_session, monkeypatch):
    from app.models import InterviewPlan

    _make_pro(db_session)
    job_id = _seed_job(db_session).id

    calls = {"n": 0}

    def fake_generate(job_arg, resume_text=""):
        calls["n"] += 1
        return {
            "role_summary": "Focus on procurement.",
            "question_groups": [{"category": "Behavioral", "questions": ["Tell me about yourself."]}],
            "schedule": [{"day": 1, "minutes": 45, "focus": "Research Boeing."}],
            "day_of_tips": ["Arrive early."],
        }

    monkeypatch.setattr("app.interview.generate_interview_plan", fake_generate)

    r1 = signed_in_client.post(f"/interview/{job_id}", follow_redirects=True)
    assert "Research Boeing" in r1.get_data(as_text=True)
    assert db_session.query(InterviewPlan).count() == 1
    assert calls["n"] == 1

    # Second POST does not re-generate (cached).
    signed_in_client.post(f"/interview/{job_id}", follow_redirects=True)
    assert calls["n"] == 1
    assert db_session.query(InterviewPlan).count() == 1


# ── Dashboard upsell ──────────────────────────────────────────────────────────


def test_dashboard_shows_interview_prep_button(signed_in_client, db_session):
    from app.models import Job, JobMatch, SavedSearch, User
    from app.sync import rebuild_matches_for_user

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    job = Job(
        source="test", company="Stripe", title="Senior Product Manager",
        normalized_title="senior product manager",
        url="https://example.com/jobs/iv-dash", city="nyc",
        location="New York, NY", description="Requires 8+ years.",
        vertical="pm", is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    rebuild_matches_for_user(user.id)
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "Interview Prep" in body
    assert f"/interview/{job.id}" in body
