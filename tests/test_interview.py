"""AI interview prep (Pro-only feature): plan sanitization, the salary-
expectation math, the Pro gate, storage/caching (incl. legacy-plan
regeneration), and the dashboard upsell button."""
import json


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


def _seed_job(db_session, salary_min=None, salary_max=None, salary_label=None):
    from app.models import Job

    job = Job(
        source="test", company="Boeing", title="Supply Chain Manager",
        normalized_title="supply chain manager",
        url="https://example.com/jobs/iv-1", city="charleston-sc",
        location="North Charleston, SC", description="Lead procurement.",
        vertical="scm", is_technical=False,
        salary_min=salary_min, salary_max=salary_max, salary_label=salary_label,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _fake_plan():
    return {
        "role_summary": "Focus on procurement.",
        "company_background": {
            "overview": "Boeing builds commercial and defense aircraft.",
            "facts": ["787s are assembled in North Charleston."],
        },
        "questions_to_ask": [
            {"category": "About the role", "questions": ["What does success look like in 90 days?"]},
        ],
        "years_experience": 8,
        "salary_estimate": {"low": 120000, "high": 150000, "note": "Anchor high."},
        "salary": {
            "basis": "market", "market_label": "Charleston, SC", "market_count": 5,
            "years_experience": 8, "experience_label": "7-9 years",
            "ask_low": 120000, "ask_high": 150000, "target": 135000,
            "ask_low_fmt": "$120K", "ask_high_fmt": "$150K", "target_fmt": "$135K",
            "posted_label": "", "note": "Anchor high.",
        },
    }


# ── Plan sanitization ─────────────────────────────────────────────────────────


def test_sanitize_plan_coerces_and_bounds():
    from app.interview import sanitize_plan

    dirty = {
        "role_summary": 123,  # wrong type
        "company_background": {
            "overview": "Real overview.",
            "facts": ["fact1", 5, "fact2"],
            "evil_key": "dropped",
        },
        "questions_to_ask": [
            {"category": "About the role", "questions": ["q1", 5, "q2"]},
            "not-a-dict",
        ],
        "years_experience": "12",  # numeric string coerced
        "salary_estimate": {"low": "150000", "high": 99_000_000, "note": 7},
        "evil_key": "dropped",
    }
    clean = sanitize_plan(dirty)
    assert set(clean.keys()) == {
        "role_summary", "company_background",
        "years_experience", "salary_estimate",
    }
    assert clean["role_summary"] == ""  # non-str coerced
    assert clean["company_background"]["overview"] == "Real overview."
    assert clean["company_background"]["facts"] == ["fact1", "fact2"]  # non-str dropped
    assert "questions_to_ask" not in clean  # section removed
    assert clean["years_experience"] == 12
    assert clean["salary_estimate"]["low"] == 150000
    assert clean["salary_estimate"]["high"] is None  # above sane cap
    assert clean["salary_estimate"]["note"] == ""


def test_sanitize_plan_handles_garbage():
    from app.interview import sanitize_plan

    clean = sanitize_plan("not-a-dict")
    assert clean["company_background"] == {"overview": "", "facts": []}
    assert clean["years_experience"] is None


def test_sanitize_plan_caps_two_facts():
    from app.interview import sanitize_plan

    clean = sanitize_plan({
        "company_background": {"overview": "o", "facts": ["f1", "f2", "f3", "f4"]},
    })
    assert clean["company_background"]["facts"] == ["f1", "f2"]


def test_sanitize_plan_omits_questions_section():
    from app.interview import sanitize_plan

    clean = sanitize_plan({
        "questions_to_ask": [
            {"category": "About the role", "questions": ["q1", "q2"]},
        ],
    })
    assert "questions_to_ask" not in clean


# ── Salary expectations ───────────────────────────────────────────────────────


def test_bucket_for_years():
    from app.interview import bucket_for_years

    assert bucket_for_years(None) is None
    assert bucket_for_years(0) == "0-2"
    assert bucket_for_years(3) == "3-6"
    assert bucket_for_years(8) == "7-9"
    assert bucket_for_years(25) == "10+"


def test_salary_expectation_prefers_market_data(db_session):
    from app.interview import build_salary_expectation

    job = _seed_job(db_session)
    plan = {"years_experience": 12, "salary_estimate": {"low": 90000, "high": 95000, "note": "n"}}
    points = [100_000, 120_000, 140_000, 160_000, 180_000]
    sal = build_salary_expectation(job, plan, points, "Charleston, SC")
    assert sal["basis"] == "market"
    assert sal["market_count"] == 5
    assert sal["experience_label"] == "10+ years"
    # 10+ band = 75th..100th percentile of the observed points
    assert sal["ask_low"] == 160000
    assert sal["ask_high"] == 180000
    assert sal["ask_low_fmt"] == "$160K"
    assert sal["note"] == "n"


def test_salary_expectation_falls_back_to_posting(db_session):
    from app.interview import build_salary_expectation

    job = _seed_job(db_session, salary_min=110_000, salary_max=130_000, salary_label="$110K–$130K")
    plan = {"years_experience": 4, "salary_estimate": {}}
    sal = build_salary_expectation(job, plan, [], "Charleston, SC")
    assert sal["basis"] == "posting"
    assert sal["ask_low"] == 110000
    assert sal["ask_high"] == 130000
    assert sal["posted_label"] == "$110K–$130K"


def test_salary_expectation_falls_back_to_model_estimate(db_session):
    from app.interview import build_salary_expectation

    job = _seed_job(db_session)
    plan = {"years_experience": None, "salary_estimate": {"low": 95000, "high": 115000, "note": ""}}
    sal = build_salary_expectation(job, plan, [], "Charleston, SC", fallback_bucket="3-6")
    assert sal["basis"] == "model"
    assert sal["ask_low"] == 95000
    assert sal["ask_high"] == 115000


def test_salary_expectation_none_when_no_signal(db_session):
    from app.interview import build_salary_expectation

    job = _seed_job(db_session)
    plan = {"years_experience": 5, "salary_estimate": {}}
    assert build_salary_expectation(job, plan, [], "Charleston, SC") is None


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


# ── Generation, caching, legacy regeneration ─────────────────────────────────


def test_pro_user_generates_and_caches_plan(signed_in_client, db_session, monkeypatch):
    from app.models import InterviewPlan

    _make_pro(db_session)
    job_id = _seed_job(db_session).id

    calls = {"n": 0}

    def fake_generate(job_arg, resume_text="", **kwargs):
        calls["n"] += 1
        return _fake_plan()

    monkeypatch.setattr("app.interview.generate_interview_plan", fake_generate)

    r1 = signed_in_client.post(f"/interview/{job_id}", follow_redirects=True)
    body = r1.get_data(as_text=True)
    assert "commercial and defense aircraft" in body      # company background
    assert "What you should ask them" not in body          # questions section removed
    assert "$120K" in body and "$150K" in body            # salary expectations
    assert db_session.query(InterviewPlan).count() == 1
    assert calls["n"] == 1

    # Second POST does not re-generate (cached).
    signed_in_client.post(f"/interview/{job_id}", follow_redirects=True)
    assert calls["n"] == 1
    assert db_session.query(InterviewPlan).count() == 1


def test_template_trims_cached_plans_to_two_bullets(signed_in_client, db_session):
    """Plans cached before the 2-bullet cap can hold more — the template
    slices the facts list to 2. The Questions-to-ask section is no longer
    rendered at all, even for plans that still carry it."""
    from app.models import InterviewPlan

    user = _make_pro(db_session)
    job_id = _seed_job(db_session).id
    plan = _fake_plan()
    plan["company_background"]["facts"] = ["fact-a", "fact-b", "fact-c"]
    plan["questions_to_ask"] = [
        {"category": "About the role", "questions": ["q-one", "q-two", "q-three"]},
    ]
    db_session.add(InterviewPlan(user_id=user.id, job_id=job_id, content_json=json.dumps(plan)))
    db_session.commit()

    body = signed_in_client.get(f"/interview/{job_id}").get_data(as_text=True)
    assert "fact-a" in body and "fact-b" in body and "fact-c" not in body
    # Questions section removed — no questions render, and its header is gone.
    assert "What you should ask them" not in body
    assert "q-one" not in body


def test_legacy_plan_regenerates_into_new_shape(signed_in_client, db_session, monkeypatch):
    """Plans stored in the old 14-day-schedule shape render the generate CTA
    and are replaced (not duplicated) on the next POST."""
    from app.models import InterviewPlan

    user = _make_pro(db_session)
    job_id = _seed_job(db_session).id
    legacy = {
        "role_summary": "Old summary.",
        "question_groups": [{"category": "Behavioral", "questions": ["old q"]}],
        "schedule": [{"day": 1, "minutes": 45, "focus": "Old focus."}],
        "day_of_tips": ["old tip"],
    }
    db_session.add(InterviewPlan(user_id=user.id, job_id=job_id, content_json=json.dumps(legacy)))
    db_session.commit()

    # GET treats the legacy plan as absent — offer to build the new package.
    body = signed_in_client.get(f"/interview/{job_id}").get_data(as_text=True)
    assert "Old focus." not in body
    assert "Build my interview prep" in body

    monkeypatch.setattr(
        "app.interview.generate_interview_plan",
        lambda job_arg, resume_text="", **kwargs: _fake_plan(),
    )
    signed_in_client.post(f"/interview/{job_id}", follow_redirects=True)
    rows = db_session.query(InterviewPlan).all()
    assert len(rows) == 1  # replaced in place, no duplicate
    assert "company_background" in rows[0].content_json


# ── Dashboard upsell ──────────────────────────────────────────────────────────


def test_dashboard_shows_interview_prep_button(signed_in_client, db_session):
    from app.models import Job, SavedSearch, User
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
