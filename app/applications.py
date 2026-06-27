"""Durable application history.

A user "applies" by downloading a Tailored Resume. That stamps the (volatile)
JobMatch row for the board badge, and — via :func:`record_application` — writes
a permanent AppliedJob row so the application survives the nightly rebuild and
can be analysed up to a year later. See app/models.py::AppliedJob.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .models import AppliedJob, Job

RETENTION_DAYS = 365


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Coerce to naive UTC. SQLite stores naive datetimes, so values read back
    from the DB are tz-naive — normalize both sides before any comparison."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def record_application(db, user_id: int, job: Job, applied_at: datetime | None = None) -> AppliedJob:
    """Upsert the AppliedJob row for (user, job). Idempotent.

    First application wins the timestamp — re-downloading the tailored resume
    later doesn't move the original applied-at date (so analysis stays honest).
    Passing ``applied_at`` lets the backfill restore real historical dates.
    """
    existing = db.execute(
        select(AppliedJob).where(
            AppliedJob.user_id == user_id, AppliedJob.url == job.url
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Keep details current (company/title may have been cleaned up) but
        # never overwrite the original applied_at.
        existing.job_id = job.id
        existing.company = job.company
        existing.title = job.title
        existing.city = job.city
        existing.location = job.location
        existing.salary_label = job.salary_label
        existing.vertical = job.vertical
        if applied_at is not None and _naive_utc(applied_at) < _naive_utc(existing.applied_at):
            existing.applied_at = applied_at
        return existing

    row = AppliedJob(
        user_id=user_id,
        job_id=job.id,
        company=job.company,
        title=job.title,
        url=job.url,
        city=job.city,
        location=job.location,
        salary_label=job.salary_label,
        vertical=job.vertical,
        applied_at=applied_at or datetime.now(timezone.utc),
    )
    db.add(row)
    # autoflush is off session-wide, so flush now — otherwise a second call for
    # the same (user, url) before a commit wouldn't see this pending row and
    # would insert a duplicate that trips the unique constraint at commit.
    db.flush()
    return row


def applied_urls_for_user(db, user_id: int) -> set[str]:
    """URLs the user has applied to — used to flag the board badge."""
    return set(
        db.execute(
            select(AppliedJob.url).where(AppliedJob.user_id == user_id)
        ).scalars().all()
    )


def applications_for_user(db, user_id: int) -> list[AppliedJob]:
    """All of a user's applications, most recent first."""
    return list(
        db.execute(
            select(AppliedJob)
            .where(AppliedJob.user_id == user_id)
            .order_by(AppliedJob.applied_at.desc())
        ).scalars().all()
    )


def prune_old_applications(db, days: int = RETENTION_DAYS) -> int:
    """Delete applications older than ``days`` (default ~1 year). Returns count."""
    # Naive cutoff: SQLite stores applied_at naive, so compare like-for-like.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    rows = db.execute(
        select(AppliedJob).where(AppliedJob.applied_at < cutoff)
    ).scalars().all()
    for row in rows:
        db.delete(row)
    return len(rows)
