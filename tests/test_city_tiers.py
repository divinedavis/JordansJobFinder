"""Paid city tiers: 3 free, 5 ($9.99/mo), 10 ($19.99/mo) via Stripe.
Covers the validation ceiling, plan-sized form slots, webhook fulfillment,
downgrade on cancellation, and the billing page."""


def _set_city_limit(db_session, email, limit):
    from app.models import Subscription, User

    user = db_session.query(User).filter(User.email == email).one()
    sub = db_session.query(Subscription).filter(
        Subscription.user_id == user.id
    ).one_or_none()
    if sub is None:
        sub = Subscription(user_id=user.id)
        db_session.add(sub)
    sub.city_limit = limit
    db_session.commit()
    return user


# ── Validation ceiling ────────────────────────────────────────────────────────


def test_validation_enforces_plan_ceiling(app):
    from app.searches import validate_saved_search

    with app.app_context():
        four = ["New York, NY", "Atlanta, GA", "Miami, FL", "Boise, ID"]
        assert validate_saved_search("technical-product-manager", "3-6", four).ok is False
        assert validate_saved_search(
            "technical-product-manager", "3-6", four, max_cities=5
        ).ok is True
        ten = [
            "New York, NY", "Atlanta, GA", "Miami, FL", "Boise, ID",
            "Columbia, SC", "Madison, WI", "Chattanooga, TN", "Reno, NV",
            "Spokane, WA", "Toledo, OH",
        ]
        assert validate_saved_search(
            "technical-product-manager", "3-6", ten, max_cities=10
        ).ok is True
        assert validate_saved_search(
            "technical-product-manager", "3-6", ten, max_cities=5
        ).ok is False


# ── Form slots follow the plan ────────────────────────────────────────────────


def test_free_user_gets_three_city_slots(signed_in_client):
    body = signed_in_client.get("/search").get_data(as_text=True)
    assert 'name="city_3"' in body
    assert 'name="city_4"' not in body
    assert "Upgrade" in body  # upsell note links to billing


def test_five_city_plan_gets_five_slots_and_saves_five(signed_in_client, db_session):
    from app.models import SavedSearch, User

    _set_city_limit(db_session, "user@example.com", 5)
    body = signed_in_client.get("/search").get_data(as_text=True)
    assert 'name="city_5"' in body
    assert 'name="city_6"' not in body

    resp = signed_in_client.post("/search", data={
        "title_slug": "technical-product-manager",
        "experience_bucket": "7-9",
        "city_1": "New York, NY",
        "city_2": "Atlanta, GA",
        "city_3": "Miami, FL",
        "city_4": "Boise, ID",
        "city_5": "Columbia, SC",
    })
    assert resp.status_code == 302
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    assert len(search.cities) == 5
    assert "Columbia, SC" in search.cities


def test_free_user_cannot_save_beyond_three(signed_in_client, db_session):
    from app.models import SavedSearch, User

    signed_in_client.post("/search", data={
        "title_slug": "technical-product-manager",
        "experience_bucket": "7-9",
        "city_1": "New York, NY",
        "city_2": "Atlanta, GA",
        "city_3": "Miami, FL",
        "city_4": "Boise, ID",  # beyond the free limit — ignored by the form read
    })
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    assert len(search.cities) == 3


# ── Webhook fulfillment + downgrade ───────────────────────────────────────────


def _completed_event(user_id, kind, stripe_sub="sub_test_123"):
    return {
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"user_id": str(user_id), "kind": kind},
            "subscription": stripe_sub,
        }},
    }


def test_webhook_sets_city_limit_for_tiers(signed_in_client, db_session, app):
    from app.models import Subscription, User
    from app.payments import handle_webhook_event

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    uid = user.id
    _set_city_limit(db_session, "user@example.com", 3)

    with app.test_request_context():
        handle_webhook_event(_completed_event(uid, "city-5"))
    db_session.expire_all()
    sub = db_session.query(Subscription).filter(Subscription.user_id == uid).one()
    assert sub.city_limit == 5
    assert sub.status == "active"
    assert sub.stripe_subscription_id == "sub_test_123"


def test_webhook_subscription_deleted_resets_to_free(signed_in_client, db_session, app):
    from app.models import Subscription, User
    from app.payments import handle_webhook_event

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    uid = user.id
    _set_city_limit(db_session, "user@example.com", 10)
    sub = db_session.query(Subscription).filter(Subscription.user_id == uid).one()
    sub.stripe_subscription_id = "sub_gone"
    db_session.commit()

    with app.test_request_context():
        handle_webhook_event({
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_gone"}},
        })
    db_session.expire_all()
    sub = db_session.query(Subscription).filter(Subscription.user_id == uid).one()
    assert sub.city_limit == 3
    assert sub.status == "cancelled"


# ── Billing page ──────────────────────────────────────────────────────────────


def test_billing_page_shows_tiers(signed_in_client):
    body = signed_in_client.get("/billing").get_data(as_text=True)
    assert "$9.99/mo" in body
    assert "$19.99/mo" in body
    assert "billing/checkout/city-5" in body
    assert "billing/checkout/city-10" in body
