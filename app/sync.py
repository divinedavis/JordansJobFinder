from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from .db import get_db
from .ingest import normalized_shared_jobs
from .matching import match_job_for_user
from .models import DailyRun, Job, JobMatch, MagicLinkToken, SavedSearch, User


def upsert_shared_jobs() -> int:
    db = get_db()
    synced = 0
    for incoming in normalized_shared_jobs():
        existing = db.execute(select(Job).where(Job.url == incoming["url"])).scalar_one_or_none()
        if existing:
            for key, value in incoming.items():
                if key == "found_at" and value is None:
                    continue
                setattr(existing, key, value)
        else:
            db.add(Job(**incoming))
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
        allowed_cities = {c for c in [search.city_1, search.city_2, search.city_3, search.city_4, search.city_5, search.city_6] if c}
        for job in jobs:
            city_display = {
                "nyc": "New York, NY",
                "atlanta": "Atlanta, GA",
                "miami": "Miami, FL",
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
        # Cleanup expired/used magic link tokens
        db.query(MagicLinkToken).filter(
            (MagicLinkToken.expires_at < datetime.now(timezone.utc))
            | (MagicLinkToken.used_at.isnot(None))
        ).delete()
        db.commit()

        run.status = "completed"
        run.notes = f"Synced {synced_jobs} shared jobs and created {matched_jobs} user matches."
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {"synced_jobs": synced_jobs, "matched_jobs": matched_jobs}
    except Exception as exc:
        run.status = "failed"
        run.notes = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise
