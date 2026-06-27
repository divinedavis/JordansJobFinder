"""The "Applied" stamp (set when a user downloads a Tailored Resume) must
survive the nightly match rebuild — otherwise the green note vanishes every
morning. Regression guard for that data loss."""

from datetime import datetime, timezone


def _seed_user_search_job(db_session):
    from app.models import Job, SavedSearch, User

    user = User(email="applied@example.com")
    user.set_password("password123")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    db_session.add(SavedSearch(
        user_id=user.id,
        vertical="pm",
        title_slug="technical-product-manager",
        experience_bucket="7-9",
        cities=["New York, NY", "Atlanta, GA", "Miami, FL",
                "Dallas, TX", "Houston, TX", "Washington, DC"],
    ))
    job = Job(
        source="test", company="Acme", title="Senior Product Manager",
        normalized_title="senior product manager",
        url="https://example.com/jobs/applied-1", city="nyc",
        location="New York, NY", description="Looking for a senior PM.",
        is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return user.id, job.id


def test_rebuild_matches_preserves_applied_at(app, db_session):
    from app.models import JobMatch
    from app.sync import rebuild_matches

    user_id, job_id = _seed_user_search_job(db_session)

    # First rebuild creates the match (confirms the job matches the search).
    assert rebuild_matches() >= 1
    jm = db_session.query(JobMatch).filter(
        JobMatch.user_id == user_id, JobMatch.job_id == job_id
    ).one()
    assert jm.applied_at is None

    # User clicks "Tailored Resume" -> applied_at stamped.
    stamp = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    jm.applied_at = stamp
    db_session.commit()

    # Nightly rebuild runs again — the stamp must carry over.
    rebuild_matches()
    db_session.expire_all()
    jm = db_session.query(JobMatch).filter(
        JobMatch.user_id == user_id, JobMatch.job_id == job_id
    ).one()
    assert jm.applied_at is not None, "Applied note was lost on rebuild"


def test_rebuild_matches_for_user_preserves_applied_at(app, db_session):
    from app.models import JobMatch
    from app.sync import rebuild_matches, rebuild_matches_for_user

    user_id, job_id = _seed_user_search_job(db_session)
    rebuild_matches()
    jm = db_session.query(JobMatch).filter(
        JobMatch.user_id == user_id, JobMatch.job_id == job_id
    ).one()
    jm.applied_at = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
    db_session.commit()

    rebuild_matches_for_user(user_id)
    db_session.expire_all()
    jm = db_session.query(JobMatch).filter(
        JobMatch.user_id == user_id, JobMatch.job_id == job_id
    ).one()
    assert jm.applied_at is not None, "Applied note was lost on per-user rebuild"
