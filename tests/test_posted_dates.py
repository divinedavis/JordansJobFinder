"""Guards for posting-date parsing.

The bug these exist for: a Gartner "VP, Product Management" posting labelled
"Posted 30+ Days Ago" sat on the NYC board. scraper.py's date parser understood
only absolute dates, so the label parsed to None, `posted_at` was stored NULL,
and every recency check downstream fell back to `found_at` — first *discovery*
time, which resets each time the job is rediscovered. The posting was therefore
permanently "fresh" no matter how old it actually was.
"""

from datetime import datetime, timedelta, timezone

import pytest

import scraper
from app.ingest import parse_posted_datetime
from app.results import _posted_display
from posted_dates import parse_relative_posted

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "label,expected_days",
    [
        ("Posted Today", 0),
        ("Just posted", 0),
        ("Posted Yesterday", 1),
        ("Posted 3 Days Ago", 3),
        ("Posted 30+ Days Ago", 30),
        ("Posted 2 Hours Ago", 0),
        ("Posted 2 Weeks Ago", 14),
    ],
)
def test_relative_labels_resolve_to_real_dates(label, expected_days):
    parsed = parse_relative_posted(label, now=NOW)
    assert parsed is not None, f"{label!r} must not parse to None"
    assert (NOW - parsed).days == expected_days


def test_unparseable_label_is_none_not_a_guess():
    assert parse_relative_posted("") is None
    assert parse_relative_posted("Rolling basis") is None


# ── The scraper's parser (the one that had the hole) ────────────────────────────


def test_scraper_parses_workday_relative_labels():
    """The exact regression: this returned None, so posted_at went in NULL."""
    parsed = scraper.parse_posted_datetime_from_label("Posted 30+ Days Ago")
    assert parsed is not None
    assert (datetime.now(timezone.utc) - parsed).days >= 29


def test_scraper_still_parses_absolute_dates():
    assert scraper.parse_posted_datetime_from_label("2026-07-31") == datetime(
        2026, 7, 31, tzinfo=timezone.utc
    )
    assert scraper.parse_posted_datetime_from_label("Jul 31, 2026") == datetime(
        2026, 7, 31, tzinfo=timezone.utc
    )
    assert scraper.parse_posted_datetime_from_label("Unknown") is None
    assert scraper.parse_posted_datetime_from_label("") is None


def test_stale_label_is_dropped_before_the_detail_fetch():
    assert scraper.posted_label_too_old("Posted 30+ Days Ago") is True
    assert scraper.posted_label_too_old("Posted 17 Days Ago") is True
    assert scraper.posted_label_too_old("Posted Today") is False
    assert scraper.posted_label_too_old("Posted Yesterday") is False


def test_unknown_label_survives_the_prefilter():
    """A missing date is a data gap, not a stale posting — the detail page is
    fetched later and usually carries a real one. Dropping here would delete
    live jobs."""
    assert scraper.posted_label_too_old("") is False
    assert scraper.posted_label_too_old("Unknown") is False
    assert scraper.posted_label_too_old("Rolling basis") is False


def test_detail_page_label_normalizes_to_an_absolute_date():
    """The detail-page path had the same hole one line over: its regex required
    whitespace right after the digits and knew only day/hour/minute, so '30+'
    and 'Weeks' were returned verbatim."""
    today = datetime.now(timezone.utc)
    assert scraper.normalize_posted_date("Posted 30+ Days Ago") == (
        today - timedelta(days=30)
    ).strftime("%B %d, %Y")
    assert scraper.normalize_posted_date("Posted 2 Weeks Ago") == (
        today - timedelta(weeks=2)
    ).strftime("%B %d, %Y")
    assert scraper.normalize_posted_date("Posted 3 Days Ago") == (
        today - timedelta(days=3)
    ).strftime("%B %d, %Y")


def test_purge_drops_a_stale_workday_posting():
    """End of the chain: the store must not keep a 30-day-old posting just
    because we discovered it this morning."""
    fresh_discovery = datetime.now(timezone.utc).isoformat()
    store = [
        {"url": "https://x/stale", "posted": "Posted 30+ Days Ago", "found_at": fresh_discovery},
        {"url": "https://x/fresh", "posted": "Posted Today", "found_at": fresh_discovery},
        {"url": "https://x/undated", "posted": "Unknown", "found_at": fresh_discovery},
    ]
    kept = {j["url"] for j in scraper.purge_old_store(store)}
    assert "https://x/stale" not in kept
    assert "https://x/fresh" in kept
    assert "https://x/undated" in kept, "undated postings are kept, not silently dropped"


# ── The ingest self-heal path ──────────────────────────────────────────────────


def test_ingest_self_heal_resolves_relative_labels():
    """`_normalize_one` backfills posted_at from posted_label when the feed
    carries no date. That backfill was a no-op for every Workday relative
    label, which is how NULL posted_at rows reached the jobs table."""
    parsed = parse_posted_datetime("Posted 30+ Days Ago")
    assert parsed is not None
    assert (datetime.now(timezone.utc) - parsed).days >= 29
    assert parse_posted_datetime("Unknown") is None


# ── The board card ─────────────────────────────────────────────────────────────


def test_card_never_renders_a_relative_label():
    """'Posted 30+ Days Ago' is scraped once and then frozen on the card; it
    tells the user nothing about when the job was actually posted."""
    for label in ("Posted 30+ Days Ago", "Posted 3 Days Ago", "Posted Yesterday", "Posted Today"):
        rendered = _posted_display(label, datetime(2026, 8, 1, tzinfo=timezone.utc))
        assert "Ago" not in rendered
        assert "Yesterday" not in rendered
        assert rendered == "Found Aug 1"


def test_card_prefers_the_resolved_posted_date():
    rendered = _posted_display(
        "Posted 3 Days Ago",
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 30, tzinfo=timezone.utc),
    )
    assert rendered == "Posted Jul 30"


def test_card_keeps_an_absolute_label():
    assert _posted_display("2026-07-31", datetime(2026, 8, 1, tzinfo=timezone.utc)) == "2026-07-31"


def test_card_handles_naive_datetimes_from_sqlite():
    """SQLite hands back naive datetimes — the helper must not raise on them."""
    assert _posted_display("Unknown", None, datetime(2026, 7, 30)) == "Posted Jul 30"
    assert _posted_display("Unknown", datetime(2026, 8, 1)) == "Found Aug 1"
    assert _posted_display("Unknown", None) == "Unknown"


# ── The duplication that caused this ───────────────────────────────────────────


def test_every_vertical_shares_one_parser():
    """Four copies of this parser existed and only two of them understood
    Workday's dialect. Re-exports must keep pointing at the shared one."""
    import scraper_finance
    import scraper_sales

    assert scraper_finance.parse_relative_posted is parse_relative_posted
    assert scraper_sales.parse_relative_posted is parse_relative_posted
