"""Public landing page: the Today's Board card shows REAL jobs (3 max) and
the What-You-Get section pitches the leaderboard instead of 'Signal'."""
from datetime import datetime, timedelta, timezone


def _fresh_pm_job(db_session, company, title, city, location, url, days_ago=0):
    from app.models import Job

    posted = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)
    job = Job(
        source="test", company=company, title=title,
        normalized_title=title.lower(), url=url, city=city,
        location=location, description="", vertical="pm",
        is_technical=True, posted_at=posted,
    )
    db_session.add(job)
    return job


def test_home_board_shows_real_jobs_capped_at_three(client, db_session):
    # Oldest first — the card keeps the NEWEST three, so Stripe (1 day older)
    # must be the one that falls off.
    _fresh_pm_job(db_session, "Stripe", "Senior Product Manager", "nyc",
                  "New York, NY", "https://example.com/jobs/home-0", days_ago=1)
    for i, (co, title) in enumerate([
        ("Datadog", "Senior Program Manager"),
        ("Okta", "Staff Product Manager"),
        ("Brex", "Principal Product Manager"),
    ], start=1):
        _fresh_pm_job(
            db_session, co, title, "nyc", "New York, NY",
            f"https://example.com/jobs/home-{i}",
        )
    db_session.commit()

    body = client.get("/").get_data(as_text=True)
    # 4 fresh jobs exist but only the 3 newest render.
    for co in ("Datadog", "Okta", "Brex"):
        assert co in body, co
    assert "Stripe" not in body
    # The card count reflects the real fresh-job total.
    assert ">4</strong>" in body


def test_home_board_empty_state_when_no_fresh_jobs(client):
    body = client.get("/").get_data(as_text=True)
    assert "Fresh roles land every morning" in body
    # No stale hardcoded placeholders.
    assert "Netflix" not in body
    assert "Airbnb" not in body


def test_home_pitches_leaderboard_not_signal(client):
    body = client.get("/").get_data(as_text=True)
    assert "Leaderboard" in body
    assert ">Signal<" not in body
