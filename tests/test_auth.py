"""Signup + login round-trips."""


def _add_pm_job(db_session, url="https://example.com/jobs/seed"):
    """A PM job that passes the open-access superuser scope (PM title, 5+ yrs)."""
    from app.models import Job
    job = Job(
        source="test", company="Acme", title="Senior Product Manager",
        normalized_title="senior product manager",
        url=url, city="nyc", location="New York, NY",
        description="We need a product manager with 8 years of experience.",
        vertical="pm", is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_signup_builds_matches_immediately(client, db_session):
    """A brand-new account must land on a populated board (same jobs as
    existing users), not wait for the next nightly sync to build its matches."""
    from app.models import JobMatch, User

    job_id = _add_pm_job(db_session).id
    response = client.post(
        "/sign-in",
        data={
            "email": "newbie@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    assert response.status_code == 302

    user = db_session.query(User).filter(User.email == "newbie@example.com").one()
    matches = db_session.query(JobMatch).filter(JobMatch.user_id == user.id).all()
    assert len(matches) >= 1
    assert any(m.job_id == job_id for m in matches)


def test_signup_creates_user_and_logs_in(client):
    response = client.post(
        "/sign-in",
        data={
            "email": "alice@example.com",
            "password": "supersecret",
            "confirm_password": "supersecret",
        },
    )
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]

    # Dashboard should now render for the newly signed-up user.
    dash = client.get("/dashboard")
    assert dash.status_code == 200


def test_signup_rejects_short_password(client):
    response = client.post(
        "/sign-in",
        data={"email": "a@b.com", "password": "short", "confirm_password": "short"},
    )
    # Redirects back to sign-in with a flash, not a 500.
    assert response.status_code == 302
    assert "/sign-in" in response.headers["Location"]


def test_signup_rejects_password_mismatch(client):
    response = client.post(
        "/sign-in",
        data={
            "email": "a@b.com",
            "password": "password123",
            "confirm_password": "different1",
        },
    )
    assert response.status_code == 302
    assert "/sign-in" in response.headers["Location"]


def test_login_with_wrong_password_fails(client):
    client.post(
        "/sign-in",
        data={
            "email": "bob@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    # New session for the login attempt.
    with client.session_transaction() as sess:
        sess.clear()
    response = client.post(
        "/login",
        data={"email": "bob@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_signup_seeds_saved_search_with_all_seven_metros(client, db_session):
    """Open access: new signups land with all 7 PM metros pre-populated."""
    from app.models import SavedSearch, User

    response = client.post(
        "/sign-in",
        data={
            "email": "newcomer@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    assert response.status_code == 302

    user = db_session.query(User).filter(User.email == "newcomer@example.com").one()
    pm_saved = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    assert set(pm_saved.cities) == {
        "New York, NY",
        "Atlanta, GA",
        "Miami, FL",
        "Dallas, TX",
        "Houston, TX",
        "Washington, DC",
        "Los Angeles, CA",
    }
    finance_saved = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "finance"
    ).one()
    assert "Philadelphia, PA" in finance_saved.cities
    assert "Baltimore, MD" in finance_saved.cities
    sales_saved = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "sales"
    ).one()
    assert sales_saved.title_slug == "entry-sales-any"
    assert "New York, NY" in sales_saved.cities
    assert "Philadelphia, PA" in sales_saved.cities


def test_sign_out_clears_session(signed_in_client):
    response = signed_in_client.post("/sign-out")
    assert response.status_code == 302
    # After signing out, dashboard should redirect again.
    dash = signed_in_client.get("/dashboard")
    assert dash.status_code == 302
