from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import stripe
from flask import current_app, url_for

from .db import get_db
from .models import Subscription, User

@dataclass
class BillingSnapshot:
    city_override_active: bool = False
    unlimited_changes_unlocked: bool = False
    status: str = "free"


class BillingConfigurationError(RuntimeError):
    pass


# Subscription tiers: checkout `kind` -> city limit + config key + label.
# Each tier also carries an AI-resume quota (see RESUME_QUOTA below).
CITY_TIERS = {
    "city-5": {"limit": 5, "price_key": "STRIPE_CITY5_PRICE_ID", "label": "5 cities + 25 resumes/mo — $4.99/mo"},
    "city-10": {"limit": 10, "price_key": "STRIPE_CITY10_PRICE_ID", "label": "10 cities + unlimited resumes — $19.99/mo"},
}
FREE_CITY_LIMIT = 3

# AI resume-creation quota per plan, keyed by city_limit.
#   3  (free)     -> 10 creations LIFETIME (resume_period_start ignored)
#   5  ($4.99/mo) -> 25 creations per month
#   10 ($19.99/mo)-> unlimited
# None means unlimited. is_lifetime[limit] says whether the cap never resets.
RESUME_QUOTA = {3: 10, 5: 25, 10: None}
RESUME_LIFETIME = {3: True, 5: False, 10: False}


def resume_quota_for(city_limit: int):
    """(allowed:int|None, is_lifetime:bool) for a plan. None allowed = unlimited."""
    limit = city_limit if city_limit in RESUME_QUOTA else 3
    return RESUME_QUOTA[limit], RESUME_LIFETIME[limit]


def _now_naive():
    """Naive UTC now — the resume/lock columns are naive DateTime (SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def stripe_configured() -> bool:
    return bool(current_app.config["STRIPE_SECRET_KEY"])


def _configure_stripe() -> None:
    secret = current_app.config["STRIPE_SECRET_KEY"]
    if not secret:
        raise BillingConfigurationError("Stripe is not configured yet.")
    stripe.api_key = secret


def _base_urls() -> tuple[str, str]:
    success = current_app.config["BASE_URL"] + url_for("web.billing", checkout="success")
    cancel = current_app.config["BASE_URL"] + url_for("web.billing", checkout="cancel")
    return success, cancel


def _get_or_create_customer(user: User, subscription: Subscription) -> str:
    _configure_stripe()
    if subscription.stripe_customer_id:
        return subscription.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        metadata={"user_id": str(user.id)},
    )
    subscription.stripe_customer_id = customer["id"]
    db = get_db()
    db.commit()
    return customer["id"]


def create_checkout_session(user: User, subscription: Subscription, kind: str) -> str:
    _configure_stripe()
    success_url, cancel_url = _base_urls()
    customer_id = _get_or_create_customer(user, subscription)

    if kind == "city-plan":
        price_id = current_app.config["STRIPE_CITY_PLAN_PRICE_ID"]
        if not price_id:
            raise BillingConfigurationError("Stripe city plan price is not configured.")
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={"user_id": str(user.id), "kind": kind},
            subscription_data={"metadata": {"user_id": str(user.id), "kind": kind}},
        )
        return session["url"]

    if kind in CITY_TIERS:
        price_id = current_app.config[CITY_TIERS[kind]["price_key"]]
        if not price_id:
            raise BillingConfigurationError("Stripe city tier price is not configured.")
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={"user_id": str(user.id), "kind": kind},
            subscription_data={"metadata": {"user_id": str(user.id), "kind": kind}},
        )
        return session["url"]

    if kind == "unlock-changes":
        price_id = current_app.config["STRIPE_UNLOCK_PRICE_ID"]
        if not price_id:
            raise BillingConfigurationError("Stripe unlock price is not configured.")
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={"user_id": str(user.id), "kind": kind},
        )
        return session["url"]

    raise BillingConfigurationError("Unknown checkout type.")


def create_billing_portal_session(customer_id: str, return_url: str) -> str:
    """Stripe customer billing portal — lets the user update payment method,
    switch plan, or cancel. Returns the portal URL to redirect to."""
    _configure_stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer_id, return_url=return_url
    )
    return session["url"]


def fetch_checkout_session(session_id: str):
    _configure_stripe()
    return stripe.checkout.Session.retrieve(session_id)


def sync_checkout_result(session_id: str, current_user_id: int = None) -> Optional[str]:
    session = fetch_checkout_session(session_id)

    # Idempotency: only process completed sessions
    if session.get("payment_status") != "paid":
        return None

    metadata = session.get("metadata", {})
    user_id = metadata.get("user_id")
    kind = metadata.get("kind")
    if not user_id or not kind:
        return None

    # Fix #1: Verify the checkout session belongs to the requesting user
    if current_user_id is not None and int(user_id) != current_user_id:
        return None

    db = get_db()
    user = db.get(User, int(user_id))
    if not user or not user.subscription:
        return None

    subscription = user.subscription

    # Idempotency: skip if already fulfilled for this kind
    if kind == "city-plan" and subscription.city_override_active:
        return "City replacement plan is already active."
    if kind == "unlock-changes" and subscription.unlimited_changes_unlocked:
        return "Unlimited search changes are already unlocked."
    if kind in CITY_TIERS:
        return _fulfill_city_tier(db, subscription, kind, session.get("subscription"))

    if kind == "city-plan":
        subscription.city_override_active = True
        subscription.status = "active"
        stripe_subscription_id = session.get("subscription")
        if stripe_subscription_id:
            subscription.stripe_subscription_id = stripe_subscription_id
        db.commit()
        return "City replacement plan is now active."

    if kind == "unlock-changes":
        subscription.unlimited_changes_unlocked = True
        if subscription.status == "free":
            subscription.status = "active"
        db.commit()
        return "Unlimited search changes are now unlocked."

    return None


def _fulfill_city_tier(db, subscription: Subscription, kind: str, new_stripe_sub_id: Optional[str]) -> str:
    """Apply a purchased city tier. On an up/downgrade, cancel the PREVIOUS
    Stripe subscription first so the user is never double-billed. The old
    sub's customer.subscription.deleted webhook is a no-op afterwards because
    the row already points at the new subscription id."""
    tier = CITY_TIERS[kind]
    if subscription.city_limit == tier["limit"] and subscription.stripe_subscription_id == new_stripe_sub_id:
        return f"Your {tier['limit']}-city plan is already active."

    old_sub_id = subscription.stripe_subscription_id
    if old_sub_id and new_stripe_sub_id and old_sub_id != new_stripe_sub_id:
        try:
            cancel_subscription(old_sub_id)
        except Exception:
            # Never fail fulfillment over the old sub — it can be cancelled
            # manually from the Stripe dashboard if this ever throws.
            import logging
            logging.getLogger(__name__).exception("Failed to cancel previous Stripe sub %s", old_sub_id)

    subscription.city_limit = tier["limit"]
    subscription.status = "active"
    if new_stripe_sub_id:
        subscription.stripe_subscription_id = new_stripe_sub_id
    # Upgrading starts a fresh resume period (new monthly quota) and unlocks
    # the saved search so the user can immediately use the extra city slots.
    subscription.resume_credits_used = 0
    subscription.resume_period_start = _now_naive()
    subscription.search_locked_until = None
    db.commit()
    return f"Your plan now includes {tier['limit']} cities."


def cancel_subscription(subscription_id: Optional[str]) -> None:
    if not subscription_id:
        return
    _configure_stripe()
    stripe.Subscription.delete(subscription_id)


def construct_webhook_event(payload: bytes, signature: str):
    _configure_stripe()
    secret = current_app.config["STRIPE_WEBHOOK_SECRET"]
    if not secret:
        raise BillingConfigurationError("Stripe webhook secret is not configured.")
    return stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=secret)


def handle_webhook_event(event) -> None:
    event_type = event["type"]
    data = event["data"]["object"]
    db = get_db()

    if event_type == "checkout.session.completed":
        metadata = data.get("metadata", {})
        user_id = metadata.get("user_id")
        kind = metadata.get("kind")
        if not user_id or not kind:
            return
        user = db.get(User, int(user_id))
        if not user or not user.subscription:
            return
        subscription = user.subscription
        if kind == "city-plan":
            subscription.city_override_active = True
            subscription.status = "active"
            if data.get("subscription"):
                subscription.stripe_subscription_id = data.get("subscription")
        elif kind in CITY_TIERS:
            _fulfill_city_tier(db, subscription, kind, data.get("subscription"))
            return
        elif kind == "unlock-changes":
            subscription.unlimited_changes_unlocked = True
            if subscription.status == "free":
                subscription.status = "active"
        db.commit()
        return

    if event_type == "customer.subscription.deleted":
        subscription_id = data.get("id")
        if not subscription_id:
            return
        subscription = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == subscription_id)
            .one_or_none()
        )
        if not subscription:
            return
        subscription.city_override_active = False
        subscription.city_limit = FREE_CITY_LIMIT
        subscription.status = "cancelled"
        subscription.current_period_end = datetime.now(timezone.utc)
        db.commit()


def resume_quota_state(subscription, city_limit: int) -> dict:
    """Current AI-resume quota for a subscription, applying the monthly reset
    for paid tiers. Returns {allowed, used, remaining, unlimited, is_lifetime}.
    Mutates+commits the row if a monthly period has rolled over."""
    allowed, is_lifetime = resume_quota_for(city_limit)
    if allowed is None:
        return {"allowed": None, "used": subscription.resume_credits_used or 0,
                "remaining": None, "unlimited": True, "is_lifetime": False}
    used = subscription.resume_credits_used or 0
    if not is_lifetime:
        # Monthly reset: roll the window if 30+ days have passed.
        start = subscription.resume_period_start
        if start is None or (_now_naive() - start).days >= 30:
            subscription.resume_credits_used = 0
            subscription.resume_period_start = _now_naive()
            get_db().commit()
            used = 0
    return {"allowed": allowed, "used": used, "remaining": max(0, allowed - used),
            "unlimited": False, "is_lifetime": is_lifetime}


def consume_resume_credit(subscription, city_limit: int) -> bool:
    """Try to spend one AI-resume creation. Returns True if allowed (and
    increments the counter), False if the user is out of quota."""
    state = resume_quota_state(subscription, city_limit)
    if state["unlimited"]:
        return True
    if state["remaining"] <= 0:
        return False
    subscription.resume_credits_used = (subscription.resume_credits_used or 0) + 1
    get_db().commit()
    return True
