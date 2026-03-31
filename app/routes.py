import logging

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFError

from .catalog import DEFAULT_CITIES, TITLE_LABELS, city_choices, experience_choices, title_choices
from .db import get_db
from .matching import choose_cities, city_from_slug, is_superuser_email
from .models import SavedSearch, Subscription, User
from .payments import (
    BillingConfigurationError,
    cancel_subscription,
    construct_webhook_event,
    create_checkout_session,
    handle_webhook_event,
    stripe_configured,
    sync_checkout_result,
)
from .results import group_matches_by_city, load_db_matches, preview_matches
from .searches import (
    can_change_search,
    requires_paid_city_override,
    revert_to_free_cities,
    validate_saved_search,
)
from .security import verify_turnstile

logger = logging.getLogger(__name__)

web = Blueprint("web", __name__)


# ── CSRF error handler ──
@web.app_errorhandler(CSRFError)
def handle_csrf_error(e):
    flash("Your session expired. Please try again.", "error")
    return redirect(request.referrer or url_for("web.home"))


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    db = get_db()
    user = db.get(User, user_id)
    # Fix #2: Check is_active on every request
    if user and not user.is_active:
        session.clear()
        return None
    return user


def require_user():
    user = current_user()
    if user:
        return user
    flash("Please sign in first.", "error")
    return None


def ensure_subscription(user: User, db):
    if user.subscription:
        return user.subscription
    subscription = Subscription(user_id=user.id)
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


@web.get("/")
def home():
    user = current_user()
    return render_template(
        "home.html",
        user=user,
        title_options=title_choices(),
        experience_options=experience_choices(),
        free_cities=DEFAULT_CITIES,
    )


@web.route("/sign-in", methods=["GET", "POST"])
def sign_in():
    if request.method == "POST":
        turnstile_token = request.form.get("cf-turnstile-response", "")
        turnstile_ok, turnstile_err = verify_turnstile(
            turnstile_token, request.remote_addr
        )
        if not turnstile_ok and current_app.config.get("TURNSTILE_SECRET_KEY"):
            flash(turnstile_err or "Bot verification failed.", "error")
            return redirect(url_for("web.sign_in"))

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not email:
            flash("Email is required.", "error")
            return redirect(url_for("web.sign_in"))
        if not password:
            flash("Password is required.", "error")
            return redirect(url_for("web.sign_in"))
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("web.sign_in"))
        if len(password) > 128:
            flash("Password must be 128 characters or fewer.", "error")
            return redirect(url_for("web.sign_in"))

        db = get_db()
        user = db.query(User).filter(User.email == email).one_or_none()
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("web.sign_in"))

        # Fix #9: Generic message to prevent email enumeration
        if user:
            flash("Unable to create account. Try logging in instead.", "error")
            return redirect(url_for("web.login"))

        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
        ensure_subscription(user, db)
        user.set_password(password)
        db.commit()
        session.clear()
        session["user_id"] = user.id
        session.permanent = True
        logger.info("Account created user_id=%d ip=%s", user.id, request.remote_addr)
        flash("Account created.", "success")
        return redirect(url_for("web.dashboard"))

    return render_template(
        "sign_in.html",
        user=current_user(),
        auth_mode="signup",
        turnstile_site_key=current_app.config.get("TURNSTILE_SITE_KEY", ""),
    )


@web.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        turnstile_token = request.form.get("cf-turnstile-response", "")
        turnstile_ok, turnstile_err = verify_turnstile(
            turnstile_token, request.remote_addr
        )
        if not turnstile_ok and current_app.config.get("TURNSTILE_SECRET_KEY"):
            flash(turnstile_err or "Bot verification failed.", "error")
            return redirect(url_for("web.login"))

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email:
            flash("Email is required.", "error")
            return redirect(url_for("web.login"))
        if not password:
            flash("Password is required.", "error")
            return redirect(url_for("web.login"))

        db = get_db()
        user = db.query(User).filter(User.email == email).one_or_none()
        if not user or not user.check_password(password):
            logger.warning("Failed login attempt email=%s ip=%s", email, request.remote_addr)
            flash("Invalid email or password.", "error")
            return redirect(url_for("web.login"))

        # Fix #2: Check is_active on login
        if not user.is_active:
            logger.warning("Login attempt on deactivated account user_id=%d ip=%s", user.id, request.remote_addr)
            flash("Invalid email or password.", "error")
            return redirect(url_for("web.login"))

        session.clear()
        session["user_id"] = user.id
        session.permanent = True
        logger.info("Successful login user_id=%d ip=%s", user.id, request.remote_addr)
        flash("Signed in.", "success")
        return redirect(url_for("web.dashboard"))

    return render_template(
        "sign_in.html",
        user=current_user(),
        auth_mode="login",
        turnstile_site_key=current_app.config.get("TURNSTILE_SITE_KEY", ""),
    )


@web.get("/dashboard")
def dashboard():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    db = get_db()
    user = db.get(User, user.id)
    saved_search = user.saved_search
    matches = load_db_matches(saved_search)
    preview = preview_matches(saved_search) if not matches else []
    return render_template(
        "dashboard.html",
        user=user,
        saved_search=saved_search,
        matches=matches,
        preview_matches=preview,
        grouped_matches=group_matches_by_city(matches) if matches else {},
        title_labels=TITLE_LABELS,
    )


@web.get("/matches")
def matches():
    return redirect(url_for("web.dashboard"))


@web.get("/settings")
def settings():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    db = get_db()
    user = db.get(User, user.id)
    return render_template(
        "settings.html",
        user=user,
        saved_search=user.saved_search,
        title_labels=TITLE_LABELS,
        free_cities=DEFAULT_CITIES,
        is_superuser=is_superuser_email(user.email),
    )


@web.get("/billing")
def billing():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    db = get_db()
    user = db.get(User, user.id)
    checkout_status = request.args.get("checkout")
    session_id = request.args.get("session_id")
    if checkout_status == "success" and session_id:
        try:
            message = sync_checkout_result(session_id, user.id)
            if message:
                flash(message, "success")
        except BillingConfigurationError as exc:
            logger.error("Billing error on checkout sync: %s", exc)
            flash("Billing is temporarily unavailable. Please try again later.", "error")
        return redirect(url_for("web.billing"))

    if checkout_status == "cancel":
        flash("Stripe checkout was cancelled.", "warning")
        return redirect(url_for("web.billing"))

    return render_template(
        "billing.html",
        user=user,
        stripe_configured=stripe_configured(),
        publishable_key=current_app.config["STRIPE_PUBLISHABLE_KEY"],
        is_superuser=is_superuser_email(user.email),
    )


@web.post("/billing/checkout/<kind>")
def billing_checkout(kind: str):
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    if kind not in {"city-plan", "unlock-changes"}:
        abort(404)

    db = get_db()
    user = db.get(User, user.id)
    if is_superuser_email(user.email):
        flash("Super-user access is already active on this account.", "success")
        return redirect(url_for("web.billing"))
    subscription = ensure_subscription(user, db)
    try:
        checkout_url = create_checkout_session(user, subscription, kind)
    except BillingConfigurationError as exc:
        logger.error("Billing error on checkout creation: %s", exc)
        flash("Billing is temporarily unavailable. Please try again later.", "error")
        return redirect(url_for("web.billing"))

    return redirect(checkout_url)


@web.post("/billing/cancel-city-plan")
def cancel_city_plan():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    db = get_db()
    user = db.get(User, user.id)
    if is_superuser_email(user.email):
        flash("Super-user access does not use a paid city plan.", "warning")
        return redirect(url_for("web.billing"))
    subscription = ensure_subscription(user, db)
    try:
        cancel_subscription(subscription.stripe_subscription_id)
    except BillingConfigurationError as exc:
        logger.error("Billing error on cancel: %s", exc)
        flash("Billing is temporarily unavailable. Please try again later.", "error")
        return redirect(url_for("web.billing"))
    subscription.city_override_active = False
    subscription.status = "free"
    if user.saved_search:
        revert_to_free_cities(user.saved_search)
    db.commit()
    flash("City plan cancelled. Your search has been reset to New York, Atlanta, and Miami.", "success")
    return redirect(url_for("web.billing"))


@web.route("/search", methods=["GET", "POST"])
def saved_search():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    db = get_db()
    user = db.get(User, user.id)
    subscription = ensure_subscription(user, db)

    if request.method == "POST":
        title_slug = request.form.get("title_slug", "").strip()
        experience_bucket = request.form.get("experience_bucket", "").strip()
        city_1 = request.form.get("city_1", "").strip()
        city_2 = request.form.get("city_2", "").strip()
        city_3 = request.form.get("city_3", "").strip()
        selected_cities = choose_cities(
            city_from_slug(city_1),
            city_from_slug(city_2),
            city_from_slug(city_3),
        )

        validation = validate_saved_search(title_slug, experience_bucket, selected_cities)
        if not validation.ok:
            flash(validation.error, "error")
            return redirect(url_for("web.saved_search"))

        if user.saved_search and not can_change_search(
            user.saved_search.change_count,
            subscription.unlimited_changes_unlocked,
            user.email,
        ):
                flash("You have used your free search changes. Unlock unlimited changes to continue.", "error")
                return redirect(url_for("web.dashboard"))

        if user.saved_search:
            search = user.saved_search
            search.change_count += 1
        else:
            search = SavedSearch(user_id=user.id)
            db.add(search)

        is_paid_city_override = requires_paid_city_override(selected_cities, user.email)
        if is_paid_city_override and not subscription.city_override_active:
            flash("Custom cities require the $2.99 monthly city plan.", "error")
            return redirect(url_for("web.saved_search"))

        search.title_slug = title_slug
        search.experience_bucket = experience_bucket
        search.city_1, search.city_2, search.city_3 = selected_cities
        search.is_paid_city_override = is_paid_city_override
        db.commit()
        flash("Saved search updated.", "success")
        return redirect(url_for("web.dashboard"))

    selected_search = user.saved_search
    return render_template(
        "saved_search.html",
        user=user,
        saved_search=selected_search,
        title_options=title_choices(),
        city_options=city_choices(),
        experience_options=experience_choices(),
        free_cities=DEFAULT_CITIES,
        can_use_custom_cities=subscription.city_override_active or is_superuser_email(user.email),
        is_superuser=is_superuser_email(user.email),
    )


@web.post("/account/delete")
def delete_account():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    db = get_db()
    user = db.get(User, user.id)
    logger.info("Account deleted user_id=%d ip=%s", user.id, request.remote_addr)
    if user.subscription:
        try:
            cancel_subscription(user.subscription.stripe_subscription_id)
        except BillingConfigurationError:
            pass
        user.subscription.city_override_active = False
        user.subscription.unlimited_changes_unlocked = False
        user.subscription.status = "cancelled"
        if user.saved_search:
            revert_to_free_cities(user.saved_search)
    db.delete(user)
    db.commit()
    session.clear()
    flash("Your account and saved search history have been deleted.", "success")
    return redirect(url_for("web.home"))


@web.post("/sign-out")
def sign_out():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("web.home"))


@web.post("/stripe/webhook")
def stripe_webhook():
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = construct_webhook_event(payload, signature)
        handle_webhook_event(event)
    except BillingConfigurationError:
        return jsonify({"error": "stripe_not_configured"}), 503
    except Exception:
        return jsonify({"error": "invalid_webhook"}), 400
    return jsonify({"received": True})
