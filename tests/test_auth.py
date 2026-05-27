"""Signup + login round-trips."""


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


def test_signup_seeds_saved_search_with_all_six_metros(client, db_session):
    """Open access: new signups land with all 6 metros pre-populated."""
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
    saved = db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id).one()
    assert saved.vertical == "pm"
    assert set(saved.cities) == {
        "New York, NY",
        "Atlanta, GA",
        "Miami, FL",
        "Dallas, TX",
        "Houston, TX",
        "Washington, DC",
    }


def test_sign_out_clears_session(signed_in_client):
    response = signed_in_client.post("/sign-out")
    assert response.status_code == 302
    # After signing out, dashboard should redirect again.
    dash = signed_in_client.get("/dashboard")
    assert dash.status_code == 302
