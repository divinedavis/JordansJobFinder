"""Shared posting-date parsing.

Every ATS hands back a date in its own dialect, and Workday's is *relative*
("Posted Today", "Posted 5 Days Ago", "Posted 30+ Days Ago"). The finance and
sales scrapers each grew an identical copy of this parser; scraper.py grew a
weaker third copy that understood only absolute dates, which is how a Gartner
posting labelled "Posted 30+ Days Ago" reached the PM board (unparseable date →
NULL posted_at → every recency check silently fell back to the *discovery*
time, so the job looked brand new forever).

One copy, imported everywhere. `scraper_finance` / `scraper_sales` re-export
these names so their own importers (scraper_it / scraper_hr / scraper_scm)
keep working unchanged.
"""

import re
from datetime import datetime, timedelta, timezone

RELATIVE_UNITS = {
    "minute": lambda n: timedelta(minutes=n),
    "hour": lambda n: timedelta(hours=n),
    "day": lambda n: timedelta(days=n),
    "week": lambda n: timedelta(weeks=n),
    "month": lambda n: timedelta(days=n * 30),
    "year": lambda n: timedelta(days=n * 365),
}

_RELATIVE_RE = re.compile(r"(\d+)\+?\s*(minute|hour|day|week|month|year)s?")


def parse_relative_posted(text, now=None):
    """Parse Workday's relative postedOn into a UTC datetime, or None.

    Handles 'Posted Today', 'Posted Yesterday', 'Posted 3 Days Ago',
    'Posted 30+ Days Ago', 'Posted 2 Hours Ago', 'Just posted', and falls back
    to ISO 8601 for the ATSs that send a real timestamp.

    `now` is injectable so tests don't have to reason about wall-clock drift.
    """
    if not text:
        return None
    t = text.lower().strip()
    now = now or datetime.now(timezone.utc)
    if "today" in t or "just posted" in t or "moments ago" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = _RELATIVE_RE.search(t)
    if m:
        # '30+ Days Ago' is a floor, not an estimate — Workday caps the counter
        # there. Treating it as exactly 30 days is the youngest the posting can
        # possibly be, so a recency filter built on it errs toward keeping.
        return now - RELATIVE_UNITS[m.group(2)](int(m.group(1)))
    # ISO fallback (some ATSs use this)
    return parse_iso(t)


def parse_iso(text):
    """Parse an ISO 8601 timestamp; return a UTC datetime or None."""
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00").replace("z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def first_truthy_date(*candidates):
    """Return the first non-None datetime from the candidates."""
    for c in candidates:
        if c is not None:
            return c
    return None
