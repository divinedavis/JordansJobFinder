from datetime import datetime, timezone

import pytest

from app.ingest import parse_posted_datetime


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
