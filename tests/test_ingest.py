from datetime import datetime, timezone

import pytest

from app.ingest import _normalize_one, parse_posted_datetime


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("May 29, 2026", datetime(2026, 5, 29, tzinfo=timezone.utc)),
        ("2026-05-28", datetime(2026, 5, 28, tzinfo=timezone.utc)),
        # ISO 8601 timestamps must parse so posted_at is populated and the
        # 2-day recency filter uses the real posting date (not found_at).
        ("2026-04-30T16:35:42Z", datetime(2026, 4, 30, 16, 35, 42, tzinfo=timezone.utc)),
        ("2026-05-13T15:01:40.285Z", datetime(2026, 5, 13, 15, 1, 40, 285000, tzinfo=timezone.utc)),
    ],
)
def test_parses_known_formats(raw, expected):
    assert parse_posted_datetime(raw) == expected


def test_iso_with_offset_is_tz_aware():
    dt = parse_posted_datetime("2026-05-26T08:12:52-04:00")
    assert dt is not None and dt.tzinfo is not None
    # 08:12:52-04:00 == 12:12:52 UTC
    assert dt.astimezone(timezone.utc).hour == 12


def test_unparseable_returns_none():
    assert parse_posted_datetime("") is None
    assert parse_posted_datetime(None) is None
    assert parse_posted_datetime("Unknown") is None


def test_normalize_backfills_posted_at_from_label():
    # Regression: a feed entry with a real posted_label but NULL posted_at
    # must get posted_at derived from the label, otherwise the recency filter
    # falls back to found_at and an old job (e.g. Feb 11) looks fresh forever.
    job = {
        "url": "https://example.com/job/1",
        "posted_label": "2026-02-11T03:57:07Z",
        "posted_at": None,
        "found_at": "2026-05-30T09:58:27Z",
    }
    out = _normalize_one(job, "pm")
    assert out["posted_at"] == datetime(2026, 2, 11, 3, 57, 7, tzinfo=timezone.utc)


def test_normalize_leaves_posted_at_none_when_label_unparseable():
    job = {"url": "https://example.com/job/2", "posted_label": "Unknown", "posted_at": None}
    out = _normalize_one(job, "pm")
    assert out["posted_at"] is None


def test_blocked_company_is_dropped_from_ingest(monkeypatch):
    """Regression: jobs from a blocklisted company (e.g. Scale AI) must never
    reach the dashboard, regardless of which scraper feed surfaced them."""
    from app import ingest

    monkeypatch.setattr(ingest, "load_shared_jobs", lambda: [
        {"company": "Scale AI", "title": "Product Manager", "url": "https://x/1"},
        {"company": "scale ai", "title": "Program Manager", "url": "https://x/2"},
        {"company": "Google", "title": "Program Manager", "url": "https://x/3"},
        {"company": "google", "title": "Product Manager", "url": "https://x/4"},
        {"company": "Celonis", "title": "Product Manager", "url": "https://x/5"},
        {"company": "celonis", "title": "Program Manager", "url": "https://x/6"},
        {"company": "TJX", "title": "Program Manager", "url": "https://x/8"},
        {"company": "tjx", "title": "Product Manager", "url": "https://x/9"},
        {"company": "Postman", "title": "Product Manager", "url": "https://x/7"},
    ])
    monkeypatch.setattr(ingest, "load_finance_jobs", lambda: [])
    monkeypatch.setattr(ingest, "load_sales_jobs", lambda: [])
    monkeypatch.setattr(ingest, "load_it_jobs", lambda: [])

    companies = {job["company"] for job in ingest.normalized_shared_jobs()}
    assert companies == {"Postman"}


def test_upsert_survives_duplicate_url_in_one_batch(app, monkeypatch):
    """Regression: two feed entries sharing a URL in a single batch must not
    blow up the sync. autoflush is off, so the second entry can't see the
    first's pending row; before the fix this added a second Job and the whole
    run died at commit with "UNIQUE constraint failed: jobs.url", freezing
    everyone's matches and tailored resumes."""
    from app import sync
    from app.db import get_db
    from app.models import Job
    from sqlalchemy import func, select

    def _make(title):
        return {
            "source": "successfactors-sales",
            "company": "The Hershey Company",
            "title": title,
            "normalized_title": title.lower(),
            "url": "https://careers.thehersheycompany.com/job/dup-1362262700/",
            "city": "miami",
            "location": "Tampa, FL, US",
            "description": "",
            "salary_label": "",
            "posted_label": "2026-06-01",
            "posted_at": None,
            "found_at": None,
            "vertical": "sales",
        }

    batch = [_make("Territory Sales Associate"), _make("Territory Sales Associate (Winter Haven, FL)")]
    monkeypatch.setattr(sync, "normalized_shared_jobs", lambda: batch)

    with app.app_context():
        synced = sync.upsert_shared_jobs()  # must not raise
        db = get_db()
        # Both entries counted, but only one row exists for the shared URL,
        # and the last-write-wins on its mutable fields.
        assert synced == 2
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        row = db.scalar(select(Job))
        assert row.title == "Territory Sales Associate (Winter Haven, FL)"
