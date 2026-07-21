"""Data / Business Analyst vertical (added 2026-07-19)."""


def test_analyst_title_heuristic(app):
    from app.matching import title_is_analyst

    for title in (
        "Data Analyst", "Senior Business Analyst", "BI Analyst",
        "Business Intelligence Analyst", "Product Analyst",
        "Business Systems Analyst", "Reporting Analyst",
        "Marketing Analyst", "Product Operations Specialist",
    ):
        assert title_is_analyst(title), title
    for title in (
        # Finance vocabulary stays on the finance track.
        "Financial Analyst", "Credit Analyst", "Tax Analyst",
        # Management and off-role stay out.
        "Director of Analytics", "VP, Business Intelligence",
        "Software Engineer", "Data Analytics Intern",
    ):
        assert not title_is_analyst(title), title
    # Senior ICs excluded only for entry-level (0-2) users.
    assert title_is_analyst("Senior Data Analyst")
    assert not title_is_analyst("Senior Data Analyst", entry_only=True)


def test_analyst_matching_uses_experience(app):
    from app.matching import match_job_for_user

    desc = "Requires 3+ years of experience with SQL and dashboards."
    # 5-year candidate qualifies for a 3+ years role.
    assert match_job_for_user(
        "data-business-analyst", "3-6", "Data Analyst", desc,
        None, None, "u@example.com", resume_years=5,
    )
    # 1-year candidate does not.
    assert not match_job_for_user(
        "data-business-analyst", "0-2", "Data Analyst", desc,
        None, None, "u@example.com", resume_years=1,
    )
    # No stated years -> passes (no salary floor either).
    assert match_job_for_user(
        "data-business-analyst", "3-6", "Business Analyst", "",
        None, None, "u@example.com",
    )


def test_analyst_is_selectable_and_wired():
    from app.catalog import (
        ANALYST_DEFAULT_CITIES,
        SELECTABLE_TITLES,
        TITLE_KEYWORDS,
        TITLE_VERTICALS,
        VERTICAL_DEFAULT_CITIES,
    )

    assert any(t["slug"] == "data-business-analyst" for t in SELECTABLE_TITLES)
    assert TITLE_VERTICALS["data-business-analyst"] == "analyst"
    assert "data-business-analyst" in TITLE_KEYWORDS
    assert VERTICAL_DEFAULT_CITIES["analyst"] == ANALYST_DEFAULT_CITIES
    assert ANALYST_DEFAULT_CITIES[0] == "New York, NY"


def test_analyst_scraper_wiring():
    from scraper_analyst import ANALYST_SEARCH_TERMS, title_is_analyst

    assert "data analyst" in ANALYST_SEARCH_TERMS
    assert title_is_analyst("Business Intelligence Analyst")
    assert not title_is_analyst("Financial Analyst")


def test_selecting_analyst_adds_tab(signed_in_client, db_session):
    from app.models import SavedSearch, User

    resp = signed_in_client.post("/search", data={
        "ack_lock": "1",
        "title_slug": "data-business-analyst", "experience_bucket": "3-6",
    })
    assert resp.status_code == 302
    assert "tab=analyst" in resp.headers["Location"]

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "analyst"
    ).one()
    from app.catalog import ALL_CITY_LABELS
    assert list(search.cities) == list(ALL_CITY_LABELS)

    body = signed_in_client.get("/dashboard?tab=analyst").get_data(as_text=True)
    assert "Data analyst, business analyst" in body


def test_analyst_board_keeps_a_week(app, signed_in_client, db_session):
    from datetime import datetime, timedelta, timezone

    from app.models import Job, SavedSearch, User
    from app.results import load_db_matches
    from app.sync import rebuild_matches_for_user

    signed_in_client.post("/search", data={
        "ack_lock": "1", "title_slug": "data-business-analyst",
        "experience_bucket": "3-6",
    })
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    five_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
    job = Job(
        source="test", company="TransUnion", title="Data Analyst",
        normalized_title="data analyst",
        url="https://example.com/jobs/an-1", city="chicago",
        location="Chicago, IL", description="", vertical="analyst",
        is_technical=False, posted_at=five_days_ago,
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id
    rebuild_matches_for_user(user.id)
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "analyst"
    ).one()
    matches = load_db_matches(search)
    assert any(m["id"] == job_id for m in matches)
