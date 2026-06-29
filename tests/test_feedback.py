"""Feedback button: public submission + owner-only review inbox."""
import os

from app.models import Feedback


def test_feedback_page_loads_for_anonymous(client):
    resp = client.get("/feedback")
    assert resp.status_code == 200
    assert b"feedback" in resp.data.lower()


def test_feedback_link_in_nav(client):
    # The button must be reachable from the landing page nav.
    resp = client.get("/")
    assert b'href="/feedback"' in resp.data


def test_anonymous_can_submit_feedback(client, db_session):
    resp = client.post(
        "/feedback",
        data={"message": "Love the app!", "email": "guest@example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    rows = db_session.query(Feedback).all()
    assert len(rows) == 1
    assert rows[0].message == "Love the app!"
    assert rows[0].email == "guest@example.com"
    assert rows[0].user_id is None
    assert rows[0].is_resolved is False


def test_signed_in_feedback_records_user_and_email(signed_in_client, db_session):
    resp = signed_in_client.post(
        "/feedback", data={"message": "Add salary filters please"}, follow_redirects=False
    )
    assert resp.status_code == 302
    row = db_session.query(Feedback).one()
    assert row.message == "Add salary filters please"
    assert row.email == "user@example.com"
    assert row.user_id is not None


def test_empty_feedback_is_rejected(client, db_session):
    resp = client.post("/feedback", data={"message": "   "}, follow_redirects=False)
    assert resp.status_code == 302
    assert db_session.query(Feedback).count() == 0


def test_feedback_is_length_capped(client, db_session):
    client.post("/feedback", data={"message": "x" * 9000}, follow_redirects=False)
    row = db_session.query(Feedback).one()
    assert len(row.message) == 5000


def test_admin_inbox_hidden_from_regular_user(signed_in_client):
    # Open-access users are "superusers" for matching, but NOT feedback admins.
    resp = signed_in_client.get("/feedback/admin")
    assert resp.status_code == 404


def test_admin_inbox_hidden_from_anonymous(client):
    resp = client.get("/feedback/admin", follow_redirects=False)
    # Redirected to sign-in, never shown the inbox.
    assert resp.status_code == 302
    assert "/sign-in" in resp.headers["Location"]


def test_owner_sees_submitted_feedback(superuser_client, db_session):
    # A visitor's feedback lands in the table...
    db_session.add(Feedback(email="visitor@example.com", message="Owner should see this"))
    db_session.commit()
    # ...and the owner can read it in the inbox.
    resp = superuser_client.get("/feedback/admin")
    assert resp.status_code == 200
    assert b"Owner should see this" in resp.data


def test_owner_can_toggle_resolved(superuser_client, db_session):
    superuser_client.post("/feedback", data={"message": "triage me"})
    row = db_session.query(Feedback).one()
    assert row.is_resolved is False

    resp = superuser_client.post(f"/feedback/{row.id}/resolve", follow_redirects=False)
    assert resp.status_code == 302
    db_session.expire_all()
    assert db_session.query(Feedback).one().is_resolved is True


def test_non_admin_cannot_resolve(signed_in_client, db_session):
    db_session.add(Feedback(email="visitor@example.com", message="protected"))
    db_session.commit()
    row = db_session.query(Feedback).one()
    resp = signed_in_client.post(f"/feedback/{row.id}/resolve")
    assert resp.status_code == 404
    db_session.expire_all()
    assert db_session.query(Feedback).one().is_resolved is False
