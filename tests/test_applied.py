"""Per-job "Applied" memory: toggle endpoint + dashboard rendering."""


def _seed_match(db_session, email="user@example.com"):
    """Attach a Job + JobMatch to the already-signed-up user, return the job id."""
    from app.models import Job, JobMatch, SavedSearch, User

    user = db_session.query(User).filter(User.email == email).one()
    saved = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id
    ).first()
    job = Job(
        source="test",
        company="Acme",
        title="Senior Product Manager",
        normalized_title="senior product manager",
        url="https://example.com/jobs/applied-1",
        city="nyc",
        location="New York, NY",
        description="Looking for a senior PM.",
        is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    db_session.add(
        JobMatch(saved_search_id=saved.id, user_id=user.id, job_id=job.id)
    )
    db_session.commit()
    return job.id, user.id


def test_toggle_marks_and_unmarks_applied(signed_in_client, db_session):
    from app.models import JobMatch

    job_id, user_id = _seed_match(db_session)

    # First POST applies.
    resp = signed_in_client.post(f"/jobs/{job_id}/applied")
    assert resp.status_code == 200
    assert resp.get_json() == {"applied": True}
    db_session.expire_all()
    jm = db_session.query(JobMatch).filter(
        JobMatch.user_id == user_id, JobMatch.job_id == job_id
    ).one()
    assert jm.applied_at is not None

    # Second POST undoes it.
    resp = signed_in_client.post(f"/jobs/{job_id}/applied")
    assert resp.status_code == 200
    assert resp.get_json() == {"applied": False}
    db_session.expire_all()
    jm = db_session.query(JobMatch).filter(
        JobMatch.user_id == user_id, JobMatch.job_id == job_id
    ).one()
    assert jm.applied_at is None


def test_toggle_requires_sign_in(client):
    resp = client.post("/jobs/1/applied")
    assert resp.status_code == 401


def test_toggle_unknown_job_is_404(signed_in_client):
    resp = signed_in_client.post("/jobs/999999/applied")
    assert resp.status_code == 404


def test_dashboard_renders_applied_toggle(signed_in_client, db_session):
    _seed_match(db_session)
    resp = signed_in_client.get("/dashboard")
    body = resp.get_data(as_text=True)
    assert "applied-toggle" in body
    assert "Mark applied" in body
    # The toggle JS must be wired up so the click persists server-side.
    assert "js/applied.js" in body
