import logging
from datetime import datetime, timezone
from typing import Optional

from flask import has_app_context
from sqlalchemy import select

from .db import get_db
from .ingest import normalized_shared_jobs
from .matching import match_job_for_user
from .models import (
    BaseResume,
    DailyRun,
    Job,
    JobMatch,
    MagicLinkToken,
    SavedSearch,
    TailoredResume,
    User,
)

logger = logging.getLogger(__name__)


def upsert_shared_jobs() -> int:
    db = get_db()
    synced = 0
    # Track rows added/touched in THIS batch by URL. autoflush is off, so a
    # pending Job isn't visible to a later select(); without this, the same URL
    # appearing twice in one batch (e.g. a job surfaced under two cities/feeds)
    # would db.add() a second row and blow up the whole sync at commit with
    # "UNIQUE constraint failed: jobs.url".
    seen_by_url: dict[str, Job] = {}
    for incoming in normalized_shared_jobs():
        url = incoming.get("url")
        if not url:
            # No usable URL → can't dedupe and the column is UNIQUE; skip it
            # rather than risk a collision on the empty string.
            continue

        target = seen_by_url.get(url)
        if target is None:
            target = db.execute(select(Job).where(Job.url == url)).scalar_one_or_none()

        if target is not None:
            for key, value in incoming.items():
                # Preserve first-seen: never refresh found_at on re-discovery.
                # Re-bumping it makes dateless jobs (posted_at NULL) look fresh
                # forever, since the recency filter falls back to found_at.
                if key == "found_at":
                    continue
                setattr(target, key, value)
        else:
            target = Job(**incoming)
            db.add(target)
        seen_by_url[url] = target
        synced += 1
    db.commit()
    return synced


def rebuild_matches() -> int:
    db = get_db()
    db.query(JobMatch).delete()
    db.commit()

    saved_searches = db.execute(select(SavedSearch)).scalars().all()
    jobs = db.execute(select(Job)).scalars().all()
    users_by_id = {user.id: user for user in db.execute(select(User)).scalars().all()}
    created = 0

    for search in saved_searches:
        allowed_cities = {c for c in (search.cities or []) if c}
        for job in jobs:
            if job.vertical != search.vertical:
                continue
            city_display = {
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
            }.get(job.city, job.location or "")
            if city_display not in allowed_cities and (job.location or "") not in allowed_cities:
                continue
            if not match_job_for_user(
                search.title_slug,
                search.experience_bucket,
                job.title,
                job.description or "",
                job.salary_min,
                job.salary_max,
                users_by_id.get(search.user_id).email if users_by_id.get(search.user_id) else None,
            ):
                continue
            db.add(
                JobMatch(
                    saved_search_id=search.id,
                    user_id=search.user_id,
                    job_id=job.id,
                )
            )
            created += 1

    db.commit()
    return created


def generate_tailored_resumes() -> int:
    """For every JobMatch whose user has a base resume, create a TailoredResume.

    Skips pairs that already have one. Failures are logged but don't abort the
    sync — one bad job shouldn't kill the rest of the run.
    """
    if not has_app_context():
        logger.warning("generate_tailored_resumes called without Flask app context; skipping")
        return 0

    from .resumes import generate_tailored_resume

    db = get_db()
    base_resumes = {
        br.user_id: br for br in db.execute(select(BaseResume)).scalars().all()
    }
    if not base_resumes:
        return 0
    users_by_id = {u.id: u for u in db.execute(select(User)).scalars().all()}
    jobs_by_id = {j.id: j for j in db.execute(select(Job)).scalars().all()}
    existing_pairs = {
        (t.user_id, t.job_id)
        for t in db.execute(select(TailoredResume)).scalars().all()
    }

    matches = db.execute(select(JobMatch)).scalars().all()
    created = 0
    for match in matches:
        if (match.user_id, match.job_id) in existing_pairs:
            continue
        base = base_resumes.get(match.user_id)
        user = users_by_id.get(match.user_id)
        job = jobs_by_id.get(match.job_id)
        if not (base and user and job):
            continue
        try:
            pdf_path = generate_tailored_resume(user=user, job=job, base_resume=base)
        except Exception as exc:
            logger.exception("Tailored resume failed user=%s job=%s: %s", user.id, job.id, exc)
            continue
        if not pdf_path:
            continue
        db.add(
            TailoredResume(
                user_id=user.id,
                job_id=job.id,
                content_text="",  # full text already lives on disk in the PDF
                pdf_path=pdf_path,
            )
        )
        created += 1
    db.commit()
    return created


def run_daily_sync(run_key: Optional[str] = None) -> dict:
    db = get_db()
    timestamp = datetime.now(timezone.utc)
    run_key = run_key or timestamp.strftime("%Y-%m-%d")

    run = db.execute(select(DailyRun).where(DailyRun.run_key == run_key)).scalar_one_or_none()
    if run is None:
        run = DailyRun(run_key=run_key, status="running", started_at=timestamp)
        db.add(run)
    else:
        run.status = "running"
        run.notes = None
        run.started_at = timestamp
        run.completed_at = None
    db.commit()
    db.refresh(run)

    try:
        synced_jobs = upsert_shared_jobs()
        matched_jobs = rebuild_matches()
        tailored = generate_tailored_resumes()
        # Cleanup expired/used magic link tokens
        db.query(MagicLinkToken).filter(
            (MagicLinkToken.expires_at < datetime.now(timezone.utc))
            | (MagicLinkToken.used_at.isnot(None))
        ).delete()
        db.commit()

        run.status = "completed"
        run.notes = (
            f"Synced {synced_jobs} shared jobs, created {matched_jobs} user matches, "
            f"generated {tailored} tailored resumes."
        )
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "synced_jobs": synced_jobs,
            "matched_jobs": matched_jobs,
            "tailored_resumes": tailored,
        }
    except Exception as exc:
        run.status = "failed"
        run.notes = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise
