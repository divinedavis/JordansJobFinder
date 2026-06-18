from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select

from .catalog import TITLE_LABELS
from .db import get_db
from .ingest import normalized_shared_jobs
from .matching import choose_cities, match_job_for_user
from .models import BaseResume, Job, JobMatch, TailoredResume


CITY_LABELS = {
    "nyc": "New York, NY",
    "atlanta": "Atlanta, GA",
    "miami": "Miami, FL",
    "dallas": "Dallas, TX",
    "houston": "Houston, TX",
    "dc": "Washington, DC",
    "york-pa": "York, PA",
    "lancaster-pa": "Lancaster, PA",
    "philadelphia-pa": "Philadelphia, PA",
    "harrisburg-pa": "Harrisburg, PA",
    "baltimore-md": "Baltimore, MD",
}


def _display_city(job: dict) -> str:
    city_value = job.get("city", "")
    return CITY_LABELS.get(city_value, job.get("location", ""))


def _posted_display(posted_label: str, found_at) -> str:
    """Return a stable, human-readable posted label.

    - If we have a real label (not Unknown/relative), use it.
    - Otherwise fall back to 'Found <Month Day>' using found_at.
    """
    label = (posted_label or "").strip()
    stale_relative = label.lower() in ("", "unknown", "posted today", "posted yesterday", "today", "yesterday")
    if not stale_relative:
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


def load_db_matches(saved_search) -> list[dict]:
    if not saved_search:
        return []

    db = get_db()
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None) - timedelta(days=2)
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
    # If the user has a base resume, every match can be tailored — the PDF is
    # generated on first download if it wasn't pre-built by the nightly sync.
    has_base_resume = db.scalar(
        select(BaseResume.id).where(BaseResume.user_id == saved_search.user_id)
    ) is not None

    matches = []
    for job_match, job in rows:
        matches.append(
            {
                "id": job.id,
                "company": job.company,
                "title": job.title,
                "url": job.url,
                "display_city": CITY_LABELS.get(job.city, job.location or ""),
                "location": job.location or CITY_LABELS.get(job.city, ""),
                "posted_label": _posted_display(job.posted_label, job.found_at),
                "salary_label": job.salary_label if job.salary_label and job.salary_label != "See posting" else "",
                "matched_at": job_match.matched_at,
                "has_tailored_resume": (job.id in tailored_job_ids) or has_base_resume,
                "applied": job_match.applied_at is not None,
            }
        )
    return matches


def preview_matches(saved_search) -> list[dict]:
    if not saved_search:
        return []

    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None) - timedelta(days=2)
    cities = {c for c in (saved_search.cities or []) if c}
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
            continue
        if not match_job_for_user(
            saved_search.title_slug,
            saved_search.experience_bucket,
            job.get("title", ""),
            job.get("description", "") or "",
            job.get("salary_min"),
            job.get("salary_max"),
            getattr(saved_search.user, "email", None),
        ):
            continue
        job["display_city"] = city_label or job.get("location", "")
        matches.append(job)
    return matches
