"""Plan enforcement: universal city cap (the >3-cities bug), the 30-day search
lock, the AI-resume quota (one monthly allowance for everyone), and the Profile
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


def test_resume_quota_is_the_same_for_every_plan(app, db_session):
    """The quota is a cost guard, not a paywall — the plan argument is dead.

    Regression guard for the 2026-08-06 outage: the quota was keyed by
    city_limit, city_limit_for() started returning the metro count, and every
    account silently dropped to the retired free tier's 10 LIFETIME creations.
    """
    from app.payments import RESUME_QUOTA_PER_MONTH, resume_quota_state

    user, sub = _sub(db_session)
    with app.test_request_context():
        for limit in (3, 5, 10, 30):  # 30 = today's metro count
            assert resume_quota_state(sub, limit) == {
                "allowed": RESUME_QUOTA_PER_MONTH, "used": 0,
                "remaining": RESUME_QUOTA_PER_MONTH,
                "unlimited": False, "is_lifetime": False,
            }


def test_resume_quota_resets_monthly_and_is_never_lifetime(app, db_session):
    from datetime import datetime, timedelta

    from app.payments import (RESUME_QUOTA_PER_MONTH, consume_resume_credit,
                              resume_quota_state)

    user, sub = _sub(db_session)
    from app.catalog import ALL_CITY_LABELS

    with app.test_request_context():
        limit = len(ALL_CITY_LABELS)
        for _ in range(RESUME_QUOTA_PER_MONTH):
            assert consume_resume_credit(sub, limit) is True
        assert consume_resume_credit(sub, limit) is False
        # Roll the monthly window back 31 days -> quota resets. Nothing is
        # lifetime any more, so no account can be permanently locked out.
        sub.resume_period_start = datetime.utcnow() - timedelta(days=31)
        db_session.commit()
        assert resume_quota_state(sub, limit)["remaining"] == RESUME_QUOTA_PER_MONTH


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
