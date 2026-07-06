"""IT project/program manager vertical: title heuristic, no-salary matching,
Florida/PA city inference, per-user tab visibility (an IT-track user must not
see finance/sales tabs), and end-to-end match building."""


# ── Title heuristic (app/matching.py) ─────────────────────────────────────────


def test_title_is_it_pm_accepts_it_flavored_pm_titles():
    from app.matching import title_is_it_pm

    for title in (
        "IT Project Manager",
        "Senior IT Program Manager",
        "Technical Project Manager",
        "ERP Program Manager",
        "Project Manager, Cloud Infrastructure",
        "Cybersecurity Program Manager",
        "PMO Project Manager",
    ):
        assert title_is_it_pm(title), title


def test_title_is_it_pm_rejects_non_it_or_non_pm_titles():
    from app.matching import title_is_it_pm

    for title in (
        "Construction Project Manager",
        "Senior Product Manager",       # product, not project/program
        "Project Manager",              # no IT signal
        "IT Support Specialist",        # IT but not project/program mgmt
        "Facilities Program Manager",
        "Marketing Program Manager",
    ):
        assert not title_is_it_pm(title), title


def test_it_vertical_matches_without_salary_or_experience(app):
    from app.matching import match_job_for_user

    # No salary on the posting — must still match (no pay required).
    assert match_job_for_user(
        "it-project-program-manager", "10+",
        "IT Project Manager", "", None, None, "frank@example.com",
    )
    # Low salary must not exclude either (no floor on this track).
    assert match_job_for_user(
        "it-project-program-manager", "10+",
        "IT Program Manager", "", 60000, 80000, "frank@example.com",
    )
    # A "5+ years" requirement suits a 10+ years candidate — must not filter.
    assert match_job_for_user(
        "it-project-program-manager", "10+",
        "Technical Project Manager", "Requires 5+ years of experience.",
        None, None, "frank@example.com",
    )


# ── City inference (scraper_it.py) ────────────────────────────────────────────


def test_it_scraper_infers_pa_and_all_florida_cities():
    from scraper_it import infer_city

    assert infer_city("Lancaster, PA") == "lancaster-pa"
    assert infer_city("Philadelphia, PA") == "philadelphia-pa"
    assert infer_city("Harrisburg, PA") == "harrisburg-pa"
    assert infer_city("Miami, FL") == "miami"
    assert infer_city("Tampa, FL") == "tampa-fl"
    assert infer_city("Orlando, FL") == "orlando-fl"
    assert infer_city("Jacksonville, FL") == "jacksonville-fl"
    # Anywhere else in Florida lands in the catch-all — never dropped.
    assert infer_city("Tallahassee, FL") == "florida-other"
    assert infer_city("Boca Raton, FL") == "miami"
    # Outside the track's scope → no city → job skipped.
    assert infer_city("New York, NY") == ""
    assert infer_city("Dallas, TX") == ""


# ── Per-user tabs ─────────────────────────────────────────────────────────────


def _convert_to_it_user(db_session, email="user@example.com"):
    """Replace the fixture user's default searches with a single IT search."""
    from app.catalog import IT_DEFAULT_CITIES
    from app.models import SavedSearch, User

    user = db_session.query(User).filter(User.email == email).one()
    db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id).delete()
    db_session.add(SavedSearch(
        user_id=user.id,
        vertical="it",
        title_slug="it-project-program-manager",
        experience_bucket="10+",
        cities=list(IT_DEFAULT_CITIES),
        is_paid_city_override=False,
    ))
    db_session.commit()
    return user.id


def test_it_user_sees_only_it_tab(signed_in_client, db_session):
    _convert_to_it_user(db_session)

    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "?tab=it" in body
    assert "?tab=finance" not in body
    assert "?tab=sales" not in body
    assert "?tab=pm" not in body
    assert "IT project and program manager roles" in body


def test_default_user_does_not_see_it_tab(signed_in_client):
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    # Single-title rule: signup seeds only the PM track now.
    assert "?tab=pm" in body
    assert "?tab=it" not in body
    assert "?tab=finance" not in body


def test_research_tabs_follow_user_verticals(signed_in_client, db_session):
    _convert_to_it_user(db_session)

    body = signed_in_client.get("/research").get_data(as_text=True)
    assert "?tab=it" in body
    assert "?tab=finance" not in body
    assert "?tab=sales" not in body


# ── Board freshness window ────────────────────────────────────────────────────


def test_it_board_keeps_a_week_of_jobs(app, signed_in_client, db_session):
    """IT roles post rarely in these metros — the board keeps 7 days, not the
    2-day window the national tracks use."""
    from datetime import datetime, timedelta, timezone

    from app.models import Job, SavedSearch
    from app.results import load_db_matches
    from app.sync import rebuild_matches_for_user

    user_id = _convert_to_it_user(db_session)
    five_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
    job = Job(
        source="test", company="Chewy", title="IT Program Manager",
        normalized_title="it program manager",
        url="https://example.com/jobs/it-week-1", city="orlando-fl",
        location="Orlando, FL", description="", vertical="it",
        is_technical=True, posted_at=five_days_ago,
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    rebuild_matches_for_user(user_id)
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user_id
    ).one()
    matches = load_db_matches(search)
    assert any(m["id"] == job_id for m in matches), (
        "5-day-old IT job fell off the board — 7-day window regressed"
    )


# ── End-to-end matching ───────────────────────────────────────────────────────


def test_it_search_matches_it_jobs_only(signed_in_client, db_session):
    from app.models import Job, JobMatch
    from app.sync import rebuild_matches_for_user

    user_id = _convert_to_it_user(db_session)

    good = Job(
        source="test", company="Jabil", title="IT Project Manager",
        normalized_title="it project manager",
        url="https://example.com/jobs/it-1", city="tampa-fl",
        location="Tampa, FL", description="Lead ERP rollouts.",
        vertical="it", is_technical=True,
    )
    construction = Job(
        source="test", company="Acme Builders", title="Construction Project Manager",
        normalized_title="construction project manager",
        url="https://example.com/jobs/it-2", city="tampa-fl",
        location="Tampa, FL", description="", vertical="it", is_technical=False,
    )
    wrong_city = Job(
        source="test", company="Jabil", title="IT Program Manager",
        normalized_title="it program manager",
        url="https://example.com/jobs/it-3", city="nyc",
        location="New York, NY", description="", vertical="it", is_technical=True,
    )
    db_session.add_all([good, construction, wrong_city])
    db_session.commit()

    rebuild_matches_for_user(user_id)
    db_session.expire_all()
    matched_job_ids = {
        m.job_id
        for m in db_session.query(JobMatch).filter(JobMatch.user_id == user_id).all()
    }
    assert good.id in matched_job_ids
    assert construction.id not in matched_job_ids
    assert wrong_city.id not in matched_job_ids
