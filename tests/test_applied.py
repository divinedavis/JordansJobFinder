"""The "Applied" stamp (set when a user downloads a Tailored Resume) must
survive the nightly match rebuild — otherwise the green note vanishes every
morning. Regression guard for that data loss."""

from datetime import datetime, timezone


def _seed_user_search_job(db_session):
    from app.models import Job, SavedSearch, User

    user = User(email="applied@example.com")
    user.set_password("Str0ng-Pass-9x")
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
        source="test", company="Datadog", title="Senior Product Manager",
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


# ── Durable application history (AppliedJob) ──────────────────────────────────


def test_record_application_is_idempotent_and_keeps_first_date(app, db_session):
    from datetime import datetime, timezone
    from app.applications import record_application
    from app.models import AppliedJob, Job

    user_id, job_id = _seed_user_search_job(db_session)
    job = db_session.get(Job, job_id)

    first = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    record_application(db_session, user_id, job, applied_at=first)
    # A later re-download must not move the original applied date.
    record_application(db_session, user_id, job, applied_at=datetime(2026, 5, 1, tzinfo=timezone.utc))
    db_session.commit()

    rows = db_session.query(AppliedJob).filter(AppliedJob.user_id == user_id).all()
    assert len(rows) == 1
    # SQLite returns naive datetimes — compare the wall-clock value, not tzinfo.
    got = rows[0].applied_at.replace(tzinfo=None)
    assert got == first.replace(tzinfo=None), f"date moved to {got}"
    assert rows[0].company == "Datadog"


def test_prune_old_applications(app, db_session):
    from datetime import datetime, timezone
    from app.applications import prune_old_applications, record_application
    from app.models import AppliedJob, Job

    user_id, job_id = _seed_user_search_job(db_session)
    job = db_session.get(Job, job_id)
    record_application(db_session, user_id, job, applied_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    db_session.commit()

    removed = prune_old_applications(db_session, days=365)
    db_session.commit()
    assert removed == 1
    assert db_session.query(AppliedJob).count() == 0


def test_applied_badge_shows_from_history_without_jobmatch_stamp(app, db_session):
    """Even with JobMatch.applied_at unset, a recorded application lights the badge."""
    from app.applications import record_application
    from app.models import Job, JobMatch
    from app.results import load_db_matches
    from app.sync import rebuild_matches

    user_id, job_id = _seed_user_search_job(db_session)
    rebuild_matches()
    jm = db_session.query(JobMatch).filter(
        JobMatch.user_id == user_id, JobMatch.job_id == job_id
    ).one()
    assert jm.applied_at is None  # never stamped on the match row

    record_application(db_session, user_id, db_session.get(Job, job_id))
    db_session.commit()

    saved = jm.saved_search
    matches = load_db_matches(saved)
    applied = {m["id"]: m["applied"] for m in matches}
    assert applied.get(job_id) is True


def test_board_shows_other_users_applied_count(app, db_session):
    """Each board card carries how many OTHER users applied to that job."""
    from app.applications import other_applicant_counts, record_application
    from app.models import Job, JobMatch, User
    from app.results import load_db_matches
    from app.sync import rebuild_matches

    user_id, job_id = _seed_user_search_job(db_session)
    rebuild_matches()
    job = db_session.get(Job, job_id)

    # Two other users apply to the same job; the owner also applies.
    for email in ("other1@example.com", "other2@example.com"):
        u = User(email=email)
        u.set_password("Str0ng-Pass-9x")
        db_session.add(u)
        db_session.commit()
        record_application(db_session, u.id, job)
    record_application(db_session, user_id, job)  # owner's own — must not count
    db_session.commit()

    counts = other_applicant_counts(db_session, [job.url], user_id)
    assert counts[job.url] == 2

    saved = db_session.query(JobMatch).filter(
        JobMatch.user_id == user_id, JobMatch.job_id == job_id
    ).one().saved_search
    by_id = {m["id"]: m["applied_by_others"] for m in load_db_matches(saved)}
    assert by_id[job_id] == 2


def test_applied_route_redirects_to_analytics(signed_in_client):
    """The Applied tab is retired — old bookmarks land on Analytics."""
    resp = signed_in_client.get("/applied")
    assert resp.status_code == 302
    assert "/analytics" in resp.headers["Location"]


def test_nav_does_not_include_applied_link(signed_in_client):
    """Regression guard: the Applied tab must not creep back into the nav."""
    resp = signed_in_client.get("/dashboard")
    body = resp.get_data(as_text=True)
    assert ">Applied</a>" not in body
