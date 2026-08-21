from metros import DISPLAY_LABELS as METRO_DISPLAY_LABELS

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select

from .applications import applied_at_by_url, naive_utc, other_applicant_counts
from .company_revenue import revenue_for
from .catalog import TITLE_LABELS
from .db import get_db
from .experience import bucket_for_years, resume_years_for_user
from .fit import build_profile, score_fit
from .ingest import normalized_shared_jobs
from .matching import choose_cities, location_matches_city, match_job_for_user
from .models import BaseResume, Job, JobMatch, TailoredResume


# Slug -> display name. Sourced from the metro registry so the label for a
# metro is defined once; retired metros stay in DISPLAY_LABELS so old rows
# still render a city name while they age off the board.
CITY_LABELS = dict(METRO_DISPLAY_LABELS)


def _display_city(job: dict) -> str:
    city_value = job.get("city", "")
    return CITY_LABELS.get(city_value, job.get("location", ""))


_RELATIVE_LABEL_RE = re.compile(
    r"\b(today|yesterday|just posted|moments ago|\d+\+?\s*(minute|hour|day|week|month|year)s?\s*ago)\b"
)


def _posted_display(posted_label: str, found_at, posted_at=None) -> str:
    """Return a stable, human-readable posted date.

    - Prefer the resolved posted_at — an absolute date that stays true tomorrow.
    - Else use the raw label, but only when it's absolute.
    - Else fall back to 'Found <Month Day>' using found_at.

    Relative labels are never rendered verbatim. 'Posted 30+ Days Ago' was
    scraped once and then sat on the card unchanged, and a phrase like
    'Posted Yesterday' is a lie the day after it's stored. Now that the
    scraper resolves those to real dates, the card shows the date instead.
    """
    if posted_at:
        dt = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
        return f"Posted {dt.strftime('%b %-d')}"
    label = (posted_label or "").strip()
    unusable = not label or label.lower() == "unknown" or _RELATIVE_LABEL_RE.search(label.lower())
    if not unusable:
        return label
    if found_at:
        dt = found_at if found_at.tzinfo else found_at.replace(tzinfo=timezone.utc)
        return f"Found {dt.strftime('%b %-d')}"
    return "Unknown"


def group_matches_by_city(matches: list[dict]) -> dict:
    grouped = {}
    for match in matches:
        city = match.get("display_city", "")
        grouped.setdefault(city, [])
        grouped[city].append(match)
    return grouped


def hidden_city_labels(saved_search) -> list[str]:
    """The cities this board's owner filtered out, cleaned. NULL/None for
    searches that predate the column, and blanks are dropped so an empty label
    can never swallow a real section.

    Stored as the DESELECTED set rather than the selected one on purpose: a
    metro that starts producing jobs later shows up by default instead of
    being silently suppressed by a filter saved months ago.
    """
    if not saved_search:
        return []
    return [c for c in (saved_search.hidden_cities or []) if c]


def visible_city_groups(grouped: dict, hidden: list[str]) -> dict:
    """The city sections to render — everything the user hasn't deselected."""
    hidden_names = {c for c in (hidden or []) if c}
    return {city: rows for city, rows in grouped.items() if city not in hidden_names}


def city_filter_options(grouped: dict, hidden: list[str]) -> list[dict]:
    """Checkbox rows for the city filter, alphabetical.

    Covers every city on the board plus any deselected city with no jobs today
    — otherwise filtering out a quiet market would leave no way to re-select it.
    """
    hidden_names = [c for c in (hidden or []) if c]
    cities = sorted(set(grouped) | set(hidden_names), key=lambda c: c.lower())
    return [
        {
            "city": city,
            "count": len(grouped.get(city, [])),
            "selected": city not in hidden_names,
        }
        for city in cities
    ]


# Board freshness window per vertical. IT project/program roles in the PA/FL
# metros post far less often than the national tracks — a 2-day window leaves
# that board nearly empty, so it keeps a week.
BOARD_WINDOW_DAYS = {"it": 7, "hr": 7, "scm": 7, "project": 7, "analyst": 7}
DEFAULT_BOARD_WINDOW_DAYS = 2


def _board_cutoff(vertical: str):
    days = BOARD_WINDOW_DAYS.get(vertical, DEFAULT_BOARD_WINDOW_DAYS)
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    ) - timedelta(days=days)


def home_board_preview(limit: int = 3):
    """Real PM jobs for the public landing card. Uses the dashboard's own
    freshness window, falling back to 7 days so a quiet holiday weekend
    doesn't leave the card empty. Returns (fresh_count, preview_rows)."""
    db = get_db()
    effective_date = case(
        (Job.posted_at.isnot(None), Job.posted_at),
        else_=Job.found_at,
    )
    rows = []
    for days in (DEFAULT_BOARD_WINDOW_DAYS, 7):
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        ) - timedelta(days=days)
        rows = db.execute(
            select(Job)
            .where(Job.vertical == "pm")
            .where(effective_date >= cutoff)
            .order_by(effective_date.desc())
        ).scalars().all()
        if rows:
            break
    preview = [
        {
            "company": job.company,
            "title": job.title,
            "display_city": CITY_LABELS.get(job.city, job.location or ""),
            "posted_label": _posted_display(job.posted_label, job.found_at, job.posted_at),
        }
        for job in rows[:limit]
    ]
    return len(rows), preview


def load_db_matches(saved_search) -> list[dict]:
    if not saved_search:
        return []

    db = get_db()
    cutoff = _board_cutoff(saved_search.vertical)
    effective_date = case(
        (Job.posted_at.isnot(None), Job.posted_at),
        else_=Job.found_at,
    )
    rows = db.execute(
        select(JobMatch, Job)
        .join(Job, Job.id == JobMatch.job_id)
        .where(JobMatch.saved_search_id == saved_search.id)
        .where(effective_date >= cutoff)
        .order_by(effective_date.desc())
    ).all()

    tailored_job_ids = set(
        db.scalars(
            select(TailoredResume.job_id).where(TailoredResume.user_id == saved_search.user_id)
        ).all()
    )
    # The durable application log is the safety net for the "Applied" badge: even
    # if a JobMatch.applied_at stamp is ever lost, a recorded application keeps
    # the green note showing for a job still on the board.
    applied_at_map = applied_at_by_url(db, saved_search.user_id)
    # Social proof: how many OTHER users applied to each board job from the site.
    other_applied = other_applicant_counts(
        db, [job.url for _, job in rows], saved_search.user_id
    )
    # If the user has a base resume, every match can be tailored — the PDF is
    # generated on first download if it wasn't pre-built by the nightly sync.
    has_base_resume = db.scalar(
        select(BaseResume.id).where(BaseResume.user_id == saved_search.user_id)
    ) is not None
    # Fit scoring: build the candidate's profile ONCE, then score each card
    # against it. Deterministic and local, so it costs nothing per card and
    # keeps working while the tailoring API is down.
    base_text = db.scalar(
        select(BaseResume.extracted_text).where(BaseResume.user_id == saved_search.user_id)
    )
    profile = (
        build_profile(base_text, resume_years_for_user(db, saved_search.user_id))
        if base_text else None
    )

    matches = []
    for job_match, job in rows:
        # Earliest of the two stamps: the JobMatch one is rebuilt nightly, the
        # history one is durable, and the grace period should run from the real
        # first application rather than whichever copy survived.
        applied_stamps = [
            naive_utc(dt)
            for dt in (job_match.applied_at, applied_at_map.get(job.url))
            if dt is not None
        ]
        matches.append(
            {
                "id": job.id,
                "company": job.company,
                "title": job.title,
                "url": job.url,
                "display_city": CITY_LABELS.get(job.city, job.location or ""),
                "location": job.location or CITY_LABELS.get(job.city, ""),
                "posted_label": _posted_display(job.posted_label, job.found_at, job.posted_at),
                "salary_label": job.salary_label if job.salary_label and job.salary_label != "See posting" else "",
                "matched_at": job_match.matched_at,
                "has_tailored_resume": (job.id in tailored_job_ids) or has_base_resume,
                "applied": bool(applied_stamps),
                "applied_at": min(applied_stamps) if applied_stamps else None,
                "applied_by_others": other_applied.get(job.url, 0),
                "revenue": revenue_for(job.company),
                "fit": score_fit(profile, job.title, job.description or ""),
            }
        )
    return matches


def preview_matches(saved_search) -> list[dict]:
    if not saved_search:
        return []

    cutoff = _board_cutoff(saved_search.vertical)
    cities = {c for c in (saved_search.cities or []) if c}
    resume_years = resume_years_for_user(get_db(), saved_search.user_id)
    experience_bucket = bucket_for_years(resume_years) or saved_search.experience_bucket
    matches = []
    for job in normalized_shared_jobs():
        posted_at = job.get("posted_at")
        found_at = job.get("found_at")
        effective = posted_at or found_at
        if isinstance(effective, str):
            try:
                effective = datetime.fromisoformat(effective.replace("Z", "+00:00"))
            except ValueError:
                effective = None
        if effective and effective.tzinfo is not None:
            effective = effective.replace(tzinfo=None)
        if effective and effective < cutoff:
            continue
        city_label = _display_city(job)
        if city_label and city_label not in cities and job.get("location") not in cities:
            if not any(
                location_matches_city(job.get("location") or "", label)
                for label in cities
            ):
                continue
        if not match_job_for_user(
            saved_search.title_slug,
            experience_bucket,
            job.get("title", ""),
            job.get("description", "") or "",
            job.get("salary_min"),
            job.get("salary_max"),
            getattr(saved_search.user, "email", None),
            resume_years=resume_years,
        ):
            continue
        job["display_city"] = city_label or job.get("location", "")
        matches.append(job)
    return matches
