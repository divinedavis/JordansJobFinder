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


def fetch_checkout_session(session_id: str):
    _configure_stripe()
    return stripe.checkout.Session.retrieve(session_id)


def sync_checkout_result(session_id: str) -> Optional[str]:
    session = fetch_checkout_session(session_id)
    metadata = session.get("metadata", {})
    user_id = metadata.get("user_id")
    kind = metadata.get("kind")
    if not user_id or not kind:
        return None

    db = get_db()
    user = db.get(User, int(user_id))
    if not user or not user.subscription:
        return None

    subscription = user.subscription
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
        subscription.status = "cancelled"
        subscription.current_period_end = datetime.now(timezone.utc)
        db.commit()
