"""Plan enforcement: universal city cap (the >3-cities bug), the 30-day search
lock, the AI-resume quota (10 lifetime / 25-mo / unlimited), and the Profile
hub."""


def _sub(db_session, email="quota@example.com"):
    from app.models import Subscription, User

    user = db_session.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(email=email)
        user.set_password("Str0ng-Pass-9x")
        db_session.add(user)
        db_session.commit()
    sub = db_session.query(Subscription).filter(Subscription.user_id == user.id).one_or_none()
    if sub is None:
        sub = Subscription(user_id=user.id)
        db_session.add(sub)
        db_session.commit()
    return user, sub


# ── City cap (the reported bug) ───────────────────────────────────────────────


def test_non_pm_track_gets_every_metro(signed_in_client, db_session):
    """Selecting a non-PM track seeds the full metro set.

    This used to cap to the plan's 3 cities. That cap is what silently dropped
    York PA off the HR board when the metro list grew to 29, so the guard now
    runs the other way: the track must get everything.
    """
    from app.catalog import ALL_CITY_LABELS
    from app.models import SavedSearch, User

    signed_in_client.post("/search", data={"ack_lock": "1", 
        "title_slug": "entry-finance-any", "experience_bucket": "0-2",
    })
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "finance"
    ).one()
    assert list(search.cities) == list(ALL_CITY_LABELS)


# ── 30-day search lock ────────────────────────────────────────────────────────


def test_saving_locks_search_for_30_days(signed_in_client, db_session):
    from datetime import datetime

    from app.models import Subscription, User

    signed_in_client.post("/search", data={"ack_lock": "1", 
        "title_slug": "technical-product-manager", "experience_bucket": "7-9",
        "city_1": "New York, NY", "city_2": "Atlanta, GA", "city_3": "Miami, FL",
    })
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    sub = db_session.query(Subscription).filter(Subscription.user_id == user.id).one()
    assert sub.search_locked_until is not None
    days = (sub.search_locked_until - datetime.utcnow()).days
    assert 28 <= days <= 30

    # A second save while locked is rejected.
    resp = signed_in_client.post("/search", data={"ack_lock": "1", 
        "title_slug": "technical-product-manager", "experience_bucket": "10+",
        "city_1": "Dallas, TX", "city_2": "Houston, TX", "city_3": "Boise, ID",
    }, follow_redirects=True)
    assert "locked" in resp.get_data(as_text=True).lower()
    db_session.expire_all()
    search = user.saved_search
    # Cities are no longer part of what locks — coverage is always complete.
    from app.catalog import ALL_CITY_LABELS
    assert list(search.cities) == list(ALL_CITY_LABELS)
    assert search.experience_bucket == "7-9", "locked search was still edited"


# ── AI-resume quota ───────────────────────────────────────────────────────────


def test_resume_quota_free_is_10_lifetime(app, db_session):
    from app.payments import consume_resume_credit, resume_quota_state

    user, sub = _sub(db_session)
    with app.test_request_context():
        state = resume_quota_state(sub, 3)
        assert state == {"allowed": 10, "used": 0, "remaining": 10,
                         "unlimited": False, "is_lifetime": True}
        for _ in range(10):
            assert consume_resume_credit(sub, 3) is True
        # 11th is blocked.
        assert consume_resume_credit(sub, 3) is False
        assert sub.resume_credits_used == 10


def test_resume_quota_pro_is_unlimited(app, db_session):
    from app.payments import consume_resume_credit

    user, sub = _sub(db_session, email="pro@example.com")
    with app.test_request_context():
        for _ in range(50):
            assert consume_resume_credit(sub, 10) is True


def test_resume_quota_plus_is_25_per_month(app, db_session):
    from datetime import datetime, timedelta

    from app.payments import consume_resume_credit, resume_quota_state

    user, sub = _sub(db_session)
    with app.test_request_context():
        for _ in range(25):
            assert consume_resume_credit(sub, 5) is True
        assert consume_resume_credit(sub, 5) is False
        # Roll the monthly window back 31 days -> quota resets.
        sub.resume_period_start = datetime.utcnow() - timedelta(days=31)
        db_session.commit()
        state = resume_quota_state(sub, 5)
        assert state["remaining"] == 25


# ── Profile hub ───────────────────────────────────────────────────────────────


def test_profile_shows_plan_resume_and_search(signed_in_client):
    body = signed_in_client.get("/profile").get_data(as_text=True)
    assert "Edit search" in body
    assert "base resume" in body.lower()
    assert "resume creations" in body.lower()


def test_save_requires_lock_acknowledgment(signed_in_client, db_session):
    """Saving without ticking the 30-day-lock acknowledgment is rejected, and
    nothing is locked."""
    from app.models import Subscription, User

    resp = signed_in_client.post("/search", data={
        "title_slug": "technical-product-manager", "experience_bucket": "7-9",
        "city_1": "New York, NY", "city_2": "Atlanta, GA", "city_3": "Miami, FL",
        # no ack_lock
    }, follow_redirects=True)
    assert "confirm you understand" in resp.get_data(as_text=True).lower()
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    sub = db_session.query(Subscription).filter(Subscription.user_id == user.id).one_or_none()
    assert sub is None or sub.search_locked_until is None


def test_search_form_shows_lock_acknowledgment(signed_in_client):
    body = signed_in_client.get("/search").get_data(as_text=True)
    assert 'name="ack_lock"' in body
    assert "locks for 30 days" in body.lower() or "lock my job title" in body.lower()
