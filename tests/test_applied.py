"""The "Applied" stamp (set when a user downloads a Tailored Resume) must
survive the nightly match rebuild — otherwise the green note vanishes every
morning. Regression guard for that data loss."""

from datetime import datetime, timedelta, timezone


def _hours_ago(hours: float) -> datetime:
    """Aware UTC timestamp `hours` in the past — the grace-period tests need to
    place an application on either side of the 24-hour line."""
    return datetime.now(timezone.utc) - timedelta(hours=hours)


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


def _seed_search_and_two_jobs(db_session, email):
    """A user with a PM search and two matching jobs on the board."""
    from app.models import Job, SavedSearch, User

    user = User(email=email)
    user.set_password("Str0ng-Pass-9x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    db_session.add(SavedSearch(
        user_id=user.id, vertical="pm",
        title_slug="technical-product-manager", experience_bucket="7-9",
        cities=["New York, NY"],
    ))
    jobs = [
        Job(
            source="test", company=company, title="Senior Product Manager",
            normalized_title="senior product manager",
            url=f"https://example.com/jobs/{slug}", city="nyc",
            location="New York, NY", description="Looking for a senior PM.",
            is_technical=True,
        )
        for company, slug in (("Datadog", "hide-1"), ("Netflix", "hide-2"))
    ]
    db_session.add_all(jobs)
    db_session.commit()
    for job in jobs:
        db_session.refresh(job)
    return user, jobs


def test_dashboard_hides_jobs_applied_to_over_24_hours_ago(client, db_session):
    """Once the 24-hour grace period is up, an applied job leaves the board —
    the record lives on Analytics instead."""
    from app.applications import record_application
    from app.sync import rebuild_matches

    user, jobs = _seed_search_and_two_jobs(db_session, "hideboard@example.com")
    rebuild_matches()
    record_application(db_session, user.id, jobs[0], applied_at=_hours_ago(25))
    db_session.commit()

    resp = client.post("/login", data={
        "email": "hideboard@example.com", "password": "Str0ng-Pass-9x",
    })
    assert resp.status_code == 302, resp.data
    body = client.get("/dashboard").get_data(as_text=True)

    assert "Netflix" in body, "an un-applied match must still show"
    assert "Datadog" not in body, "the applied job must be off the board"
    assert "1 job you already applied to is hidden" in body
    assert "/analytics" in body


def test_dashboard_applied_filter_does_not_resurrect_the_raw_feed(client, db_session, monkeypatch):
    """Applying to everything is a full board, not an empty one — the JSON-feed
    preview fallback must not kick in and put those jobs back."""
    from app.applications import record_application
    from app.sync import rebuild_matches

    user, jobs = _seed_search_and_two_jobs(db_session, "allapplied@example.com")
    rebuild_matches()
    for job in jobs:
        record_application(db_session, user.id, job, applied_at=_hours_ago(25))
    db_session.commit()

    called = {"preview": False}

    def _boom(saved_search):
        called["preview"] = True
        return []

    monkeypatch.setattr("app.routes.preview_matches", _boom)

    resp = client.post("/login", data={
        "email": "allapplied@example.com", "password": "Str0ng-Pass-9x",
    })
    assert resp.status_code == 302, resp.data
    body = client.get("/dashboard").get_data(as_text=True)

    assert called["preview"] is False
    assert "Datadog" not in body and "Netflix" not in body
    assert "applied to every job on this board" in body


def test_dashboard_keeps_jobs_applied_to_within_24_hours(client, db_session):
    """The card must stay put for a day after applying: the user is still on the
    employer's site finishing the application, and a card that vanishes the
    moment the resume downloads reads as the click having failed."""
    from app.applications import record_application
    from app.sync import rebuild_matches

    user, jobs = _seed_search_and_two_jobs(db_session, "gracewindow@example.com")
    rebuild_matches()
    record_application(db_session, user.id, jobs[0], applied_at=_hours_ago(6))
    db_session.commit()

    resp = client.post("/login", data={
        "email": "gracewindow@example.com", "password": "Str0ng-Pass-9x",
    })
    assert resp.status_code == 302, resp.data
    body = client.get("/dashboard").get_data(as_text=True)

    assert "Datadog" in body, "an applied job stays on the board for 24 hours"
    assert "Netflix" in body
    assert "hidden from this board" not in body
    # The badge is lit and says how long the card has left.
    assert "leaves in 18h" in body


def test_board_grace_expired_boundary(app):
    """Exactly 24 hours old is expired; a minute short of it is not."""
    from app.applications import board_grace_expired

    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    at_24h = {"applied": True, "applied_at": now - timedelta(hours=24)}
    just_under = {"applied": True, "applied_at": now - timedelta(hours=23, minutes=59)}

    assert board_grace_expired(at_24h, now=now) is True
    assert board_grace_expired(just_under, now=now) is False
    # Not applied, or applied with no timestamp: never hidden. A lost stamp must
    # leave the job on the board rather than silently disappear it.
    assert board_grace_expired({"applied": False, "applied_at": None}, now=now) is False
    assert board_grace_expired({"applied": True, "applied_at": None}, now=now) is False


def test_board_grace_label_counts_down():
    from app.applications import board_grace_label

    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)

    def label(**kwargs):
        return board_grace_label(
            {"applied": True, "applied_at": now - timedelta(**kwargs)}, now=now
        )

    assert label(hours=1) == "leaves in 23h"
    # Rounded up — with 22h30m left, "leaves in 22h" reads as a lost hour.
    assert label(hours=1, minutes=30) == "leaves in 23h"
    assert label(hours=23, minutes=30) == "leaves in 30 min"
    assert label(hours=24) == ""
    assert board_grace_label({"applied": True, "applied_at": None}, now=now) == ""
    assert board_grace_label({"applied": False, "applied_at": now}, now=now) == ""


def test_grace_period_runs_from_the_earliest_stamp(app, db_session):
    """The JobMatch stamp is rebuilt nightly and the history row is durable; the
    clock must start at the real first application, not the surviving copy."""
    from app.applications import board_grace_expired, record_application
    from app.models import JobMatch, User
    from app.results import load_db_matches
    from app.sync import rebuild_matches

    user, jobs = _seed_search_and_two_jobs(db_session, "earliest@example.com")
    rebuild_matches()
    job = jobs[0]
    jm = db_session.query(JobMatch).filter(
        JobMatch.user_id == user.id, JobMatch.job_id == job.id
    ).one()
    # A later JobMatch stamp (e.g. a re-download) must not extend the window.
    jm.applied_at = _hours_ago(1).replace(tzinfo=None)
    record_application(db_session, user.id, job, applied_at=_hours_ago(30))
    db_session.commit()

    user = db_session.get(User, user.id)
    match = next(
        m for m in load_db_matches(user.saved_search_for("pm")) if m["id"] == job.id
    )
    assert match["applied"] is True
    assert board_grace_expired(match) is True


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
