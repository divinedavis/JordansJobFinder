"""Regression guard for the store-retention fix.

The board went empty on any day with no brand-new postings because (1) the app
feed was built from only that run's new finds and (2) the store expired jobs
VALID_POST_DAYS after FIRST DISCOVERY. purge_old_store must instead keep jobs
whose POSTING is still recent, so a still-live posting survives across runs.
"""
from datetime import datetime, timedelta, timezone

import scraper


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_purge_keeps_recent_posting_even_if_discovered_long_ago():
    # Discovered 30 days ago, but posted today -> must stay (still a live,
    # recent posting). The old found_at-based purge wrongly dropped this.
    store = [{
        "url": "https://ex.com/1", "title": "Product Manager",
        "posted": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        "found_at": _iso(30),
    }]
    kept = scraper.purge_old_store(store)
    assert len(kept) == 1


def test_purge_drops_stale_posting():
    old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%B %d, %Y")
    store = [{
        "url": "https://ex.com/2", "title": "Product Manager",
        "posted": old, "found_at": _iso(0),
    }]
    assert scraper.purge_old_store(store) == []


def test_purge_falls_back_to_found_at_when_posting_undated():
    # No parseable posting date -> fall back to discovery date.
    recent = [{"url": "https://ex.com/3", "title": "PM", "posted": "Unknown",
               "found_at": _iso(0)}]
    stale = [{"url": "https://ex.com/4", "title": "PM", "posted": "Unknown",
              "found_at": _iso(30)}]
    assert len(scraper.purge_old_store(recent)) == 1
    assert scraper.purge_old_store(stale) == []
