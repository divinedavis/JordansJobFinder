"""Durable application history.

A user "applies" by downloading a Tailored Resume. That stamps the (volatile)
JobMatch row for the board badge, and — via :func:`record_application` — writes
a permanent AppliedJob row so the application survives the nightly rebuild and
can be analysed up to a year later. See app/models.py::AppliedJob.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import distinct, func, select

from .models import AppliedJob, Job

RETENTION_DAYS = 365
# How long an applied job keeps its place on the board before moving to
# Analytics. Applying is a click on "Tailored Resume": if the card vanished the
# same second, the click would look like it had failed, and the user would lose
# the row they still need in front of them while they finish the application on
# the employer's site. A day is long enough to come back and finish, short
# enough that the board is still a to-do list.
BOARD_GRACE_HOURS = 24


def naive_utc(dt: datetime | None) -> datetime | None:
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
        if applied_at is not None and naive_utc(applied_at) < naive_utc(existing.applied_at):
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


def applied_at_by_url(db, user_id: int) -> dict[str, datetime]:
    """URL -> applied-at (naive UTC) for everything the user has applied to.

    Drives the board badge and the 24-hour grace period, so it returns the
    timestamp rather than just the URL set.
    """
    rows = db.execute(
        select(AppliedJob.url, AppliedJob.applied_at).where(AppliedJob.user_id == user_id)
    ).all()
    return {url: naive_utc(applied_at) for url, applied_at in rows}


def board_grace_expired(match: dict, now: datetime | None = None) -> bool:
    """Has an applied job served its :data:`BOARD_GRACE_HOURS` on the board?

    ``True`` means hide it (the record lives on Analytics). An application with
    no timestamp is never hidden — no clock, no expiry — so a lost stamp keeps
    the job visible instead of silently disappearing it.
    """
    if not match.get("applied"):
        return False
    applied_at = naive_utc(match.get("applied_at"))
    if applied_at is None:
        return False
    now = naive_utc(now) if now is not None else naive_utc(datetime.now(timezone.utc))
    return applied_at <= now - timedelta(hours=BOARD_GRACE_HOURS)


def board_grace_label(match: dict, now: datetime | None = None) -> str:
    """"leaves in 18h" — how much of the grace period a card has left.

    Empty string when there's nothing to say (not applied, no timestamp, or the
    window has already closed and the card is on its way off the board).
    """
    if not match.get("applied"):
        return ""
    applied_at = naive_utc(match.get("applied_at"))
    if applied_at is None:
        return ""
    now = naive_utc(now) if now is not None else naive_utc(datetime.now(timezone.utc))
    remaining = (applied_at + timedelta(hours=BOARD_GRACE_HOURS)) - now
    seconds = remaining.total_seconds()
    if seconds <= 0:
        return ""
    if seconds < 3600:
        minutes = max(1, int(seconds // 60))
        return f"leaves in {minutes} min"
    # Round up: with 23h59m left "leaves in 23h" reads as if an hour vanished.
    hours = int(-(-seconds // 3600))
    return f"leaves in {hours}h"


def other_applicant_counts(db, urls, exclude_user_id: int) -> dict[str, int]:
    """For each job URL, how many OTHER users (not exclude_user_id) applied.

    Powers the "N others applied from this site" social-proof note on the board.
    Counts distinct users by URL (the stable cross-user job identity) so a user
    re-downloading a tailored resume never inflates the number.
    """
    urls = [u for u in set(urls or []) if u]
    if not urls:
        return {}
    rows = db.execute(
        select(AppliedJob.url, func.count(distinct(AppliedJob.user_id)))
        .where(AppliedJob.url.in_(urls))
        .where(AppliedJob.user_id != exclude_user_id)
        .group_by(AppliedJob.url)
    ).all()
    return {url: count for url, count in rows}


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
