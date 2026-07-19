"""Estimate a candidate's total years of experience from their resume text.

Deterministic (no AI call): find employment date ranges like
"Jan 2018 – Present", "March 2015 - June 2019", "2014–2017", "03/2018 – 09/2021",
merge overlapping intervals so concurrent roles (or an education range that
overlaps a job) only count once, and sum the total. The result is approximate
by design — it drives the experience *band* (0-2 / 3-6 / 7-9 / 10+), where a
±1 year error rarely changes the band.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_MONTH_RE = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_SEP = r"\s*(?:-|–|—|to|through|until)\s*"
_PRESENT = r"(?:present|current|now|today|ongoing)"

# "Jan 2018 – Present" / "March 2015 - June 2019" (period after abbreviation ok)
_MONTH_YEAR_RANGE = re.compile(
    rf"(?P<m1>{_MONTH_RE})\.?,?\s+(?P<y1>(?:19|20)\d{{2}}){_SEP}"
    rf"(?:(?P<m2>{_MONTH_RE})\.?,?\s+(?P<y2>(?:19|20)\d{{2}})|(?P<p1>{_PRESENT}))",
    re.I,
)
# "03/2018 – 09/2021" or "3/2018 - Present"
_NUM_MONTH_RANGE = re.compile(
    rf"(?P<m1>0?[1-9]|1[0-2])/(?P<y1>(?:19|20)\d{{2}}){_SEP}"
    rf"(?:(?P<m2>0?[1-9]|1[0-2])/(?P<y2>(?:19|20)\d{{2}})|(?P<p1>{_PRESENT}))",
    re.I,
)
# "2014 – 2017" or "2019 – Present" (only when not part of a month-year form,
# handled by running the more specific patterns first and blanking their spans)
_YEAR_RANGE = re.compile(
    rf"(?<![/\d])(?P<y1>(?:19|20)\d{{2}}){_SEP}(?:(?P<y2>(?:19|20)\d{{2}})|(?P<p1>{_PRESENT}))(?![/\d])",
    re.I,
)


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def _collect_intervals(text: str) -> list[tuple[int, int]]:
    now = date.today()
    now_idx = _month_index(now.year, now.month)
    intervals: list[tuple[int, int]] = []

    def add(y1: int, m1: int, y2: Optional[int], m2: Optional[int], present: bool):
        start = _month_index(y1, m1)
        end = now_idx if present else _month_index(y2, m2)
        # Sanity: no future starts, no reversed ranges, no >50-year stints,
        # nothing starting before 1970.
        if y1 < 1970 or start > now_idx or end < start or (end - start) > 600:
            return
        intervals.append((start, min(end, now_idx)))

    working = text
    for pattern, kind in ((_MONTH_YEAR_RANGE, "name"), (_NUM_MONTH_RANGE, "num")):
        def repl(match, kind=kind):
            g = match.groupdict()
            m1 = _MONTHS[g["m1"].lower().rstrip(".")] if kind == "name" else int(g["m1"])
            present = bool(g.get("p1"))
            if present:
                add(int(g["y1"]), m1, None, None, True)
            else:
                m2 = _MONTHS[g["m2"].lower().rstrip(".")] if kind == "name" else int(g["m2"])
                add(int(g["y1"]), m1, int(g["y2"]), m2, False)
            # Blank the span so the bare-year pass can't re-match its years.
            return " " * len(match.group(0))

        working = pattern.sub(repl, working)

    for match in _YEAR_RANGE.finditer(working):
        g = match.groupdict()
        if g.get("p1"):
            add(int(g["y1"]), 1, None, None, True)
        else:
            # Assume full calendar years for bare-year ranges.
            add(int(g["y1"]), 1, int(g["y2"]), 12, False)

    return intervals


def estimate_resume_years(text: Optional[str]) -> Optional[int]:
    """Total merged years across all date ranges found in the resume, rounded
    to the nearest year. None when no usable range is found."""
    if not text:
        return None
    intervals = _collect_intervals(text)
    if not intervals:
        return None

    intervals.sort()
    total_months = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end + 1:  # merge touching/overlapping ranges
            cur_end = max(cur_end, end)
        else:
            total_months += cur_end - cur_start + 1
            cur_start, cur_end = start, end
    total_months += cur_end - cur_start + 1

    years = round(total_months / 12)
    return max(0, min(years, 60))


def bucket_for_years(years) -> Optional[str]:
    """Map raw years of experience onto the catalog experience buckets."""
    if years is None:
        return None
    if years < 3:
        return "0-2"
    if years < 7:
        return "3-6"
    if years < 10:
        return "7-9"
    return "10+"


def effective_experience_bucket(db, saved_search) -> Optional[str]:
    """The bucket matching should use for this search: resume-derived years
    win; the manually saved bucket is the fallback for users with no resume
    (or a resume we couldn't date-parse)."""
    if saved_search is None:
        return None
    derived = bucket_for_years(resume_years_for_user(db, saved_search.user_id))
    return derived or saved_search.experience_bucket


def resume_years_for_user(db, user_id: int) -> Optional[int]:
    from .models import BaseResume  # local import to avoid cycles at app init

    if not user_id:
        return None
    return db.query(BaseResume.years_experience).filter(
        BaseResume.user_id == user_id
    ).scalar()
