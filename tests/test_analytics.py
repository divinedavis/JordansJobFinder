"""Analytics (year-in-review) + Research (market value) tabs.

Covers the pure aggregation helpers (deterministic with an injected ``now``)
plus route reachability / auth and the nav links.
"""
from datetime import datetime, timezone


# ── build_application_analytics ───────────────────────────────────────────────


class _AppRow:
    """Minimal stand-in for an AppliedJob row (only fields the helper reads)."""

    def __init__(self, applied_at, vertical="pm", city="nyc"):
        self.applied_at = applied_at
        self.vertical = vertical
        self.city = city


def _dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


def test_application_analytics_counts_by_week_and_month():
    from app.analytics import build_application_analytics

    now = _dt(2026, 6, 29)  # a Monday
    apps = [
        _AppRow(_dt(2026, 6, 29)),  # this week + this month
        _AppRow(_dt(2026, 6, 24)),  # earlier this month, prior week
        _AppRow(_dt(2026, 6, 23)),  # same prior week
        _AppRow(_dt(2026, 5, 10), vertical="finance", city="atlanta"),  # last month
        _AppRow(_dt(2025, 12, 1), vertical="sales", city="dallas"),  # last year
    ]
    data = build_application_analytics(apps, now=now)

    assert data["summary"]["total"] == 5
    assert data["summary"]["this_year"] == 4
    assert data["summary"]["this_month"] == 3
    assert data["summary"]["this_week"] == 1

    monthly = {row["key"]: row["count"] for row in data["monthly"]}
    assert monthly["2026-06"] == 3
    assert monthly["2026-05"] == 1
    assert monthly["2025-12"] == 1
    # 12-month contiguous window, oldest -> newest.
    assert len(data["monthly"]) == 12
    assert data["monthly"][-1]["key"] == "2026-06"

    # Prior week (Mon Jun 22) holds the Jun 23 + Jun 24 applications.
    weekly = {row["key"]: row["count"] for row in data["weekly"]}
    assert weekly["2026-06-29"] == 1
    assert weekly["2026-06-22"] == 2
    assert len(data["weekly"]) == 12

    verticals = {row["key"]: row["count"] for row in data["by_vertical"]}
    assert verticals == {"pm": 3, "finance": 1, "sales": 1}

    cities = {row["label"]: row["count"] for row in data["by_city"]}
    assert cities["New York, NY"] == 3


def test_application_analytics_empty():
    from app.analytics import build_application_analytics

    data = build_application_analytics([], now=_dt(2026, 6, 29))
    assert data["summary"]["total"] == 0
    assert data["summary"]["busiest_month"] is None
    assert all(row["count"] == 0 for row in data["monthly"])
    assert all(row["pct"] == 0 for row in data["weekly"])


def test_application_analytics_bar_pct_relative_to_max():
    from app.analytics import build_application_analytics

    now = _dt(2026, 6, 29)
    apps = [_AppRow(_dt(2026, 6, 1)) for _ in range(4)]  # 4 in June
    apps += [_AppRow(_dt(2026, 5, 1)) for _ in range(2)]  # 2 in May
    data = build_application_analytics(apps, now=now)
    by_key = {row["key"]: row for row in data["monthly"]}
    assert by_key["2026-06"]["pct"] == 100
    assert by_key["2026-05"]["pct"] == 50


# ── build_application_leaderboard ─────────────────────────────────────────────


def test_application_leaderboard_counts_and_includes_zero_users():
    from app.analytics import build_application_leaderboard

    now = _dt(2026, 6, 29)  # a Monday
    rows = [
        # jordan: 3 applications across week/month/year boundaries.
        (1, "jordan@example.com", _dt(2026, 6, 29)),   # this week + month + year
        (1, "jordan@example.com", _dt(2026, 6, 2)),    # this month + year
        (1, "jordan@example.com", _dt(2025, 11, 5)),   # last year (total only)
        # divine: 1 application earlier this year.
        (2, "divine@example.com", _dt(2026, 3, 10)),
        # newbie: outer-join row, never applied — must still be listed.
        (3, "newbie@example.com", None),
    ]
    board = build_application_leaderboard(rows, now=now)

    assert [e["name"] for e in board] == ["jordan", "divine", "newbie"]
    assert [e["rank"] for e in board] == [1, 2, 3]

    jordan, divine, newbie = board
    assert (jordan["this_week"], jordan["this_month"], jordan["this_year"], jordan["total"]) == (1, 2, 2, 3)
    assert (divine["this_week"], divine["this_month"], divine["this_year"], divine["total"]) == (0, 0, 1, 1)
    assert (newbie["this_week"], newbie["this_month"], newbie["this_year"], newbie["total"]) == (0, 0, 0, 0)


def test_analytics_page_shows_leaderboard_with_zero_apply_users(signed_in_client, db_session):
    from app.models import User

    # A second user who has never applied must still appear on the board.
    other = User(email="slacker@example.com")
    other.set_password("password123")
    db_session.add(other)
    db_session.commit()

    resp = signed_in_client.get("/analytics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Application leaderboard" in body
    assert "slacker" in body  # display name = email local part
    assert "slacker@example.com" not in body  # full addresses stay private
    assert "(you)" in body  # signed-in user highlighted


# ── build_market_research ─────────────────────────────────────────────────────


def _seed_pm_jobs(db_session):
    from app.models import Job

    def mk(url, city, lo, hi):
        return Job(
            source="test", company="Acme", title="Senior Product Manager",
            normalized_title="senior product manager", url=url, city=city,
            location=None, description="PM role.", is_technical=True,
            vertical="pm", salary_min=lo, salary_max=hi,
        )

    db_session.add_all([
        mk("https://x/1", "nyc", 180000, 220000),
        mk("https://x/2", "nyc", 200000, 260000),
        mk("https://x/3", "nyc", 240000, 300000),
        mk("https://x/4", "atlanta", 150000, 190000),
        # Garbage salary (above ceiling) must be ignored.
        mk("https://x/5", "atlanta", 9_000_000, 9_500_000),
        # Miami: a posting with no salary at all.
        mk("https://x/6", "miami", None, None),
    ])
    db_session.commit()


def test_market_research_aggregates_salary_by_city(app, db_session):
    from app.analytics import build_market_research

    _seed_pm_jobs(db_session)
    data = build_market_research(
        db_session,
        cities=["New York, NY", "Atlanta, GA", "Miami, FL"],
        vertical="pm",
        experience_bucket="7-9",
    )
    by_city = {m["city"]: m for m in data["markets"]}

    nyc = by_city["New York, NY"]
    assert nyc["has_data"] is True
    assert nyc["count"] == 3
    # Midpoints: 200k, 230k, 270k -> median 230k.
    assert nyc["median"] == 230000
    assert nyc["min"] == 200000
    assert nyc["max"] == 270000
    # Suggested ask band sits inside the observed range.
    assert nyc["ask_low"] <= nyc["ask_high"] <= nyc["max"]

    atl = by_city["Atlanta, GA"]
    assert atl["count"] == 1  # garbage row dropped

    miami = by_city["Miami, FL"]
    assert miami["has_data"] is False
    assert miami["total_postings"] == 1

    assert data["overall"]["count"] == 4
    assert data["overall"]["top_market"] == "New York, NY"


def test_market_research_includes_applied_salary_per_market(app, db_session):
    from app.analytics import build_market_research
    from app.applications import record_application
    from app.models import Job, User

    _seed_pm_jobs(db_session)
    user = User(email="applied-research@example.com")
    user.set_password("password123")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # Apply to two NYC roles (200k & 270k midpoints) and one Atlanta role (170k).
    for url in ("https://x/1", "https://x/3", "https://x/4"):
        job = db_session.query(Job).filter(Job.url == url).one()
        record_application(db_session, user.id, job)
    db_session.commit()

    data = build_market_research(
        db_session,
        cities=["New York, NY", "Atlanta, GA", "Miami, FL"],
        vertical="pm",
        experience_bucket="7-9",
        user_id=user.id,
    )
    by_city = {m["city"]: m for m in data["markets"]}

    nyc_applied = by_city["New York, NY"]["applied"]
    assert nyc_applied is not None
    assert nyc_applied["count"] == 2
    assert nyc_applied["with_salary"] == 2
    assert nyc_applied["min"] == 200000
    assert nyc_applied["max"] == 270000
    # 75th percentile of [200k, 270k] = 252.5k -> potential sits in range.
    assert nyc_applied["min"] <= nyc_applied["potential"] <= nyc_applied["max"]

    # Miami had no application -> no applied block.
    assert by_city["Miami, FL"]["applied"] is None

    assert data["applied_overall"]["count"] == 3
    assert data["applied_overall"]["top_market"] == "New York, NY"


def test_market_research_no_applications_no_applied_overall(app, db_session):
    from app.analytics import build_market_research
    from app.models import User

    _seed_pm_jobs(db_session)
    user = User(email="noapps@example.com")
    user.set_password("password123")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    data = build_market_research(
        db_session, cities=["New York, NY"], vertical="pm",
        experience_bucket="7-9", user_id=user.id,
    )
    assert data["applied_overall"] is None
    assert data["markets"][0]["applied"] is None


def test_market_research_no_data():
    # No DB rows touched: empty city list -> empty markets, no overall.
    from app.analytics import build_market_research

    class _DB:
        def execute(self, *_):
            raise AssertionError("should not query with no cities")

    data = build_market_research(_DB(), cities=[], vertical="pm", experience_bucket="7-9")
    assert data["markets"] == []
    assert data["overall"] is None


# ── routes + nav ──────────────────────────────────────────────────────────────


def test_analytics_page_requires_sign_in(client):
    assert client.get("/analytics").status_code == 302


def test_research_page_requires_sign_in(client):
    assert client.get("/research").status_code == 302


def test_analytics_page_renders(signed_in_client):
    resp = signed_in_client.get("/analytics")
    assert resp.status_code == 200
    assert "application analytics" in resp.get_data(as_text=True).lower()


def test_research_page_renders(signed_in_client):
    resp = signed_in_client.get("/research")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Market Research" in body
    # Tabs mirror the dashboard verticals.
    assert "?tab=finance" in body


def test_research_shows_seeded_market_value(signed_in_client, db_session):
    from app.models import User
    from app.sync import rebuild_matches_for_user

    _seed_pm_jobs(db_session)
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    rebuild_matches_for_user(user.id)

    resp = signed_in_client.get("/research?tab=pm")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "New York, NY" in body
    assert "Ask" in body  # suggested-ask pill rendered


def test_nav_includes_analytics_and_research(signed_in_client):
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert ">Analytics</a>" in body
    assert ">Research</a>" in body
