import json
import logging
import os
import re
from datetime import timedelta

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
from sqlalchemy import select as sa_select

from flask import send_file

from .catalog import (
    DEFAULT_CITIES,
    TITLE_LABELS,
    TITLE_VERTICALS,
    VERTICAL_DEFAULT_CITIES,
    experience_choices,
    title_choices,
)
from .db import get_db
from .matching import city_from_slug, is_admin_email, is_superuser_email
from .models import AppliedJob, BaseResume, Feedback, InterviewPlan, Job, JobMatch, SavedSearch, Subscription, TailoredResume, User
from .models import utc_now
from .resumes import (
    ResumeError,
    detect_kind,
    extract_text,
    save_base_resume,
)
from .payments import (
    BillingConfigurationError,
    cancel_subscription,
    construct_webhook_event,
    consume_resume_credit,
    create_billing_portal_session,
    create_checkout_session,
    handle_webhook_event,
    resume_quota_state,
    stripe_configured,
    sync_checkout_result,
)
from .results import group_matches_by_city, home_board_preview, load_db_matches, preview_matches
from .experience import (
    bucket_for_years,
    effective_experience_bucket,
    estimate_resume_years,
    resume_years_for_user,
)
from .applications import applications_for_user, record_application
from .analytics import (
    CITY_LABELS,
    _salary_points_for,
    build_application_analytics,
    build_application_leaderboard,
    build_market_research,
)
from .searches import (
    revert_to_free_cities,
    valid_experience_bucket,
    valid_title_slug,
    validate_saved_search,
)
from .uscities import cities_by_state, split_label, state_choices
from .security import (
    account_locked,
    clear_failed_logins,
    dummy_password_check,
    enforce_turnstile,
    hash_identifier,
    password_rejection_reason,
    register_failed_login,
)

logger = logging.getLogger(__name__)

web = Blueprint("web", __name__)


# ── CSRF error handler ──
@web.app_errorhandler(CSRFError)
def handle_csrf_error(e):
    flash("Your session expired. Please try again.", "error")
    # Only honor Referer when it points back to our own origin — otherwise
    # an attacker could craft a cross-site request whose failure redirects
    # the victim to an attacker-controlled URL.
    referrer = request.referrer or ""
    safe = referrer.startswith(request.host_url) if referrer else False
    return redirect(referrer if safe else url_for("web.home"))


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


@web.app_context_processor
def inject_admin_flag():
    """Expose `is_admin` to every template so the nav can show the
    Feedback Inbox link only to the owner."""
    user = current_user()
    return {"is_admin": is_admin_email(user.email) if user else False}


@web.app_context_processor
def inject_gtag():
    """Expose the Google Ads tag id to every page, and the sign-up conversion
    label exactly once — on the first render after a new account is created.

    The label is only surfaced (and the one-time flag consumed) when a label is
    actually configured, so before the label is set the flag survives and fires
    on the first render once it is."""
    from flask import current_app, session

    label = current_app.config.get("GOOGLE_ADS_SIGNUP_LABEL", "")
    fire_label = ""
    if label and session.get("signup_conversion"):
        session.pop("signup_conversion", None)
        fire_label = label
    return {
        "gads_id": current_app.config.get("GOOGLE_ADS_ID", ""),
        "gads_signup_label": fire_label,
    }


def ensure_subscription(user: User, db):
    if user.subscription:
        return user.subscription
    subscription = Subscription(user_id=user.id)
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def city_limit_for(user, subscription) -> int:
    """How many cities this account's saved search may hold: 3 free, 5 or 10
    via the paid tiers. The owner account always gets the maximum."""
    if is_admin_email(user.email):
        return 10
    return max(3, subscription.city_limit or 3)


def is_pro(user, subscription) -> bool:
    """Pro ($19.99) tier — 10 cities — or the owner account. Gates the AI
    interview-prep feature."""
    if is_admin_email(user.email):
        return True
    return (subscription.city_limit or 3) >= 10


SEARCH_LOCK_DAYS = 30


def _lock_search(subscription) -> None:
    """Freeze the saved search for 30 days from now (caller commits)."""
    subscription.search_locked_until = utc_now().replace(tzinfo=None) + timedelta(days=SEARCH_LOCK_DAYS)


def search_locked(user, subscription) -> bool:
    """Whether the saved search is currently frozen. The owner is never locked."""
    if is_admin_email(user.email):
        return False
    until = subscription.search_locked_until
    return until is not None and until > utc_now().replace(tzinfo=None)


@web.get("/")
def home():
    user = current_user()
    # Real jobs for the landing card — never let a data hiccup 500 the
    # public homepage.
    try:
        board_count, board_preview = home_board_preview(limit=3)
    except Exception:
        logger.exception("Home board preview failed")
        board_count, board_preview = 0, []
    return render_template(
        "home.html",
        user=user,
        title_options=title_choices(),
        experience_options=experience_choices(),
        free_cities=DEFAULT_CITIES,
        board_count=board_count,
        board_preview=board_preview,
    )


@web.route("/sign-in", methods=["GET", "POST"])
def sign_in():
    if request.method == "POST":
        turnstile_token = request.form.get("cf-turnstile-response", "")
        turnstile_err = enforce_turnstile(turnstile_token, request.remote_addr)
        if turnstile_err:
            flash(turnstile_err, "error")
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

        # Fix #9: Generic message to prevent email enumeration. Same redirect
        # target + same flash regardless of whether the email already exists,
        # so a scripted attacker can't distinguish via the response.
        if user:
            flash("Unable to create account. If this is your email, try signing in.", "error")
            return redirect(url_for("web.sign_in"))

        # Reject weak/guessable passwords only once we're actually about to
        # create the account (after the mismatch + existing-email checks, so
        # those clearer messages win first).
        weak_reason = password_rejection_reason(password, email)
        if weak_reason:
            flash(weak_reason, "error")
            return redirect(url_for("web.sign_in"))

        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
        ensure_subscription(user, db)
        user.set_password(password)
        # One job title per account: new users start with a single PM track
        # seeded with the free 3-city set (the paid tiers raise the limit to
        # 5 or 10); they can switch title/cities on /search.
        db.add(SavedSearch(
            user_id=user.id,
            vertical="pm",
            title_slug="technical-product-manager",
            experience_bucket="7-9",
            cities=list(DEFAULT_CITIES),
            is_paid_city_override=False,
        ))
        db.commit()
        # Build this user's matches now so they land on the same populated board
        # as everyone else, instead of an empty preview until the next 6 AM sync.
        try:
            from .sync import rebuild_matches_for_user
            rebuild_matches_for_user(user.id)
        except Exception:
            logger.exception("Failed to build initial matches for user_id=%d", user.id)
        session.clear()
        session["user_id"] = user.id
        session.permanent = True
        # Fire the Google Ads "Sign-ups" conversion once, on the next page.
        # Only set on real account creation — NOT on the sign-in path below.
        session["signup_conversion"] = True
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
        turnstile_err = enforce_turnstile(turnstile_token, request.remote_addr)
        if turnstile_err:
            flash(turnstile_err, "error")
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

        if user is not None and account_locked(user):
            logger.warning(
                "Login attempt on locked account user_id=%d ip=%s",
                user.id, request.remote_addr,
            )
            flash("Too many failed attempts. Try again in a few minutes.", "error")
            return redirect(url_for("web.login"))

        if not user or not user.check_password(password):
            if user is not None:
                register_failed_login(user)
                db.commit()
            else:
                # No such account: still spend a password-verification's worth
                # of time so the response can't be timed to tell registered
                # emails from unregistered ones (user enumeration).
                dummy_password_check(password)
            # Hash the submitted email — failed attempts must not log PII.
            logger.warning(
                "Failed login attempt email_hash=%s ip=%s",
                hash_identifier(email), request.remote_addr,
            )
            flash("Invalid email or password.", "error")
            return redirect(url_for("web.login"))

        # Fix #2: Check is_active on login
        if not user.is_active:
            logger.warning("Login attempt on deactivated account user_id=%d ip=%s", user.id, request.remote_addr)
            flash("Invalid email or password.", "error")
            return redirect(url_for("web.login"))

        clear_failed_logins(user)
        db.commit()
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


VERTICAL_LABELS = {
    "pm": "Product / Program / IT Manager",
    "finance": "Corporate Finance",
    "sales": "Corporate Sales",
    "it": "IT Project/Program Manager",
    "hr": "HR Coordinator+",
    "scm": "Supply Chain (SC)",
    "project": "Project Management (SC)",
}
VERTICAL_ORDER = ["pm", "finance", "sales", "it", "hr", "scm", "project"]


def user_verticals(user) -> list[str]:
    """Tabs are personal: a user only sees the verticals they have a saved
    search for (e.g. an IT-track user sees just the IT tab — no finance/sales)."""
    tabs = [v for v in VERTICAL_ORDER if user.saved_search_for(v)]
    return tabs or ["pm"]


@web.get("/dashboard")
def dashboard():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    db = get_db()
    user = db.get(User, user.id)
    tabs = user_verticals(user)
    active_tab = request.args.get("tab", "")
    if active_tab not in tabs:
        active_tab = tabs[0]
    saved_search = user.saved_search_for(active_tab)
    matches = load_db_matches(saved_search) if saved_search else []
    preview = preview_matches(saved_search) if (saved_search and not matches) else []
    resume_years = resume_years_for_user(db, user.id)
    return render_template(
        "dashboard.html",
        user=user,
        saved_search=saved_search,
        matches=matches,
        preview_matches=preview,
        grouped_matches=group_matches_by_city(matches) if matches else {},
        title_labels=TITLE_LABELS,
        active_tab=active_tab,
        tab_labels=VERTICAL_LABELS,
        tab_order=tabs,
        resume_years=resume_years,
        resume_bucket=bucket_for_years(resume_years),
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

    subscription = ensure_subscription(user, db)
    limit = city_limit_for(user, subscription)
    resume = resume_quota_state(subscription, limit)
    return render_template(
        "billing.html",
        user=user,
        stripe_configured=stripe_configured(),
        publishable_key=current_app.config["STRIPE_PUBLISHABLE_KEY"],
        is_billing_exempt=is_admin_email(user.email),
        city_limit=limit,
        resume=resume,
    )


@web.post("/billing/checkout/<kind>")
def billing_checkout(kind: str):
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    if kind not in {"city-plan", "unlock-changes", "city-5", "city-10"}:
        abort(404)

    db = get_db()
    user = db.get(User, user.id)
    # Only the owner account is billing-exempt (is_superuser_email is open
    # to every signed-in user, so it can't gate checkout).
    if is_admin_email(user.email):
        flash("The owner account already has the maximum city limit.", "success")
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
    if is_admin_email(user.email):
        flash("The owner account does not use a paid city plan.", "warning")
        return redirect(url_for("web.billing"))
    subscription = ensure_subscription(user, db)
    try:
        cancel_subscription(subscription.stripe_subscription_id)
    except BillingConfigurationError as exc:
        logger.error("Billing error on cancel: %s", exc)
        flash("Billing is temporarily unavailable. Please try again later.", "error")
        return redirect(url_for("web.billing"))
    # Reflect the downgrade immediately (the webhook is the backstop): back to
    # the free 3-city limit, keeping the user's first three chosen cities.
    subscription.city_limit = 3
    subscription.city_override_active = False
    subscription.status = "cancelled"
    if user.saved_search and len(user.saved_search.cities or []) > 3:
        user.saved_search.cities = list(user.saved_search.cities)[:3]
    db.commit()
    try:
        from .sync import rebuild_matches_for_user
        rebuild_matches_for_user(user.id)
    except Exception:
        logger.exception("Match rebuild after downgrade failed user_id=%d", user.id)
    flash("Plan cancelled. Your search keeps its first three cities.", "success")
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
        # Search lock: after the first save the whole search (title, experience,
        # cities) is frozen for 30 days. Upgrading a tier clears the lock.
        if search_locked(user, subscription):
            flash(
                f"Your search is locked until {subscription.search_locked_until:%b %-d, %Y}. "
                "Upgrade your plan to change it sooner.",
                "error",
            )
            return redirect(url_for("web.saved_search"))

        # The user must explicitly acknowledge the 30-day lock before saving.
        if not request.form.get("ack_lock"):
            flash(
                "Please confirm you understand your search locks for 30 days before saving.",
                "error",
            )
            return redirect(url_for("web.saved_search"))

        title_slug = request.form.get("title_slug", "").strip()
        experience_bucket = request.form.get("experience_bucket", "").strip()
        # Resume-derived seniority wins: when the user's resume has parseable
        # years, the manual picker is hidden on the form and the bucket is
        # filled from the resume (matching also derives live — this keeps the
        # stored row consistent for users who later delete their resume).
        derived_bucket = bucket_for_years(resume_years_for_user(db, user.id))
        if derived_bucket:
            experience_bucket = derived_bucket
        limit = city_limit_for(user, subscription)

        # Non-PM titles (finance/sales/IT/HR) select a whole track: the
        # vertical's search is created/updated with its pinned city set,
        # capped to the account's plan limit (cities are a paid feature).
        vertical = TITLE_VERTICALS.get(title_slug, "pm")

        # One job title per account: choosing a title REPLACES any other
        # track — every dashboard shows exactly one job selection at a time.
        def _enforce_single_title():
            db.query(SavedSearch).filter(
                SavedSearch.user_id == user.id,
                SavedSearch.vertical != vertical,
            ).delete(synchronize_session=False)

        if vertical != "pm":
            if not valid_title_slug(title_slug) or not valid_experience_bucket(experience_bucket):
                flash("Choose a supported title and experience level.", "error")
                return redirect(url_for("web.saved_search"))
            search = user.saved_search_for(vertical)
            if search is None:
                search = SavedSearch(user_id=user.id, vertical=vertical)
                db.add(search)
            search.title_slug = title_slug
            search.experience_bucket = experience_bucket
            search.cities = list(VERTICAL_DEFAULT_CITIES[vertical])[:limit]
            search.is_paid_city_override = False
            _enforce_single_title()
            _lock_search(subscription)
            db.commit()
            try:
                from .sync import rebuild_matches_for_user
                rebuild_matches_for_user(user.id)
            except Exception:
                logger.exception("Match rebuild after track add failed user_id=%d", user.id)
            flash(f"Your dashboard now tracks {TITLE_LABELS.get(title_slug, title_slug)}. Cities locked for 30 days.", "success")
            return redirect(url_for("web.dashboard", tab=vertical))

        raw_cities = [
            request.form.get(f"city_{i}", "").strip() for i in range(1, limit + 1)
        ]
        selected_cities = [city_from_slug(value) for value in raw_cities if value]

        validation = validate_saved_search(
            title_slug, experience_bucket, selected_cities, max_cities=limit
        )
        if not validation.ok:
            flash(validation.error, "error")
            return redirect(url_for("web.saved_search"))

        if user.saved_search:
            search = user.saved_search
            search.change_count += 1
        else:
            search = SavedSearch(user_id=user.id, vertical="pm")
            db.add(search)

        search.title_slug = title_slug
        search.experience_bucket = experience_bucket
        search.cities = list(selected_cities)
        search.is_paid_city_override = len(selected_cities) > 3
        _enforce_single_title()
        _lock_search(subscription)
        db.commit()
        try:
            from .sync import rebuild_matches_for_user
            rebuild_matches_for_user(user.id)
        except Exception:
            logger.exception("Match rebuild after search edit failed user_id=%d", user.id)
        flash("Saved search updated. Your cities are locked for 30 days.", "success")
        return redirect(url_for("web.dashboard"))

    selected_search = user.saved_search
    # State-then-city picker slots (any US city above 50k population); the
    # slot count follows the account's plan: 3 free, 5 or 10 paid.
    limit = city_limit_for(user, subscription)
    selected = list(selected_search.cities) if selected_search else list(DEFAULT_CITIES)
    selected = selected[:limit] + [""] * max(0, limit - len(selected))
    city_slots = [
        {"value": selected[i], "state": split_label(selected[i])[1]}
        for i in range(limit)
    ]
    return render_template(
        "saved_search.html",
        user=user,
        saved_search=selected_search,
        title_options=title_choices(),
        experience_options=experience_choices(),
        resume_years=resume_years_for_user(db, user.id),
        free_cities=DEFAULT_CITIES,
        city_slots=city_slots,
        city_limit=limit,
        state_options=state_choices(),
        cities_by_state=cities_by_state(),
        # NOTE: gate on is_admin_email (the single owner), NOT is_superuser_email
        # — the latter returns True for every signed-in user (open job scope), so
        # using it here would hand the paid custom-city feature to everyone.
        can_use_custom_cities=subscription.city_override_active or is_admin_email(user.email),
        is_superuser=is_superuser_email(user.email),
        is_locked=search_locked(user, subscription),
        locked_until=subscription.search_locked_until,
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


@web.get("/profile")
def profile():
    """Account hub: plan + AI-resume credits, saved-search editing, resume
    upload, and Stripe subscription management — all in one place."""
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    db = get_db()
    user = db.get(User, user.id)
    subscription = ensure_subscription(user, db)
    limit = city_limit_for(user, subscription)
    return render_template(
        "profile.html",
        user=user,
        base_resume=user.base_resume,
        subscription=subscription,
        city_limit=limit,
        resume=resume_quota_state(subscription, limit),
        is_billing_exempt=is_admin_email(user.email),
        is_locked=search_locked(user, subscription),
        locked_until=subscription.search_locked_until,
        has_stripe_customer=bool(subscription.stripe_customer_id),
    )


@web.post("/billing/portal")
def billing_portal():
    """Open the Stripe customer billing portal so the user can update their
    card, switch, or cancel their subscription."""
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    db = get_db()
    user = db.get(User, user.id)
    subscription = ensure_subscription(user, db)
    if not subscription.stripe_customer_id:
        flash("You don't have a subscription to manage yet.", "warning")
        return redirect(url_for("web.profile"))
    try:
        portal_url = create_billing_portal_session(
            subscription.stripe_customer_id,
            current_app.config["BASE_URL"] + url_for("web.profile"),
        )
    except BillingConfigurationError as exc:
        logger.error("Billing portal error: %s", exc)
        flash("Subscription management is temporarily unavailable.", "error")
        return redirect(url_for("web.profile"))
    return redirect(portal_url)


@web.post("/sign-out")
def sign_out():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("web.home"))


@web.get("/resume")
def resume_page():
    # Resume management now lives in the Profile hub.
    return redirect(url_for("web.profile"))


@web.post("/resume/upload")
def resume_upload():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))

    upload = request.files.get("resume")
    if not upload or not upload.filename:
        flash("Choose a PDF or DOCX file to upload.", "error")
        return redirect(url_for("web.resume_page"))

    raw = upload.read(current_app.config["RESUME_MAX_UPLOAD_BYTES"] + 1)
    if len(raw) > current_app.config["RESUME_MAX_UPLOAD_BYTES"]:
        flash("Resume is too large (5 MB max).", "error")
        return redirect(url_for("web.resume_page"))

    try:
        kind = detect_kind(upload.filename, upload.content_type or "")
        text = extract_text(raw, kind)
    except ResumeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("web.resume_page"))
    except Exception as exc:
        # pypdf / python-docx raise their own exception types on malformed input.
        # Surface a friendly message instead of leaking a 500 + stack trace.
        logger.warning("Resume parse failed user_id=%s: %s", user.id, exc)
        flash("That file looks corrupt. Please re-export and try again.", "error")
        return redirect(url_for("web.resume_page"))

    file_path = save_base_resume(user.id, upload.filename, raw, kind)
    resume_years = estimate_resume_years(text)
    db = get_db()
    user = db.get(User, user.id)
    if user.base_resume:
        # Replace existing record + delete previous file from disk.
        try:
            if user.base_resume.file_path and os.path.exists(user.base_resume.file_path):
                os.remove(user.base_resume.file_path)
        except OSError:
            logger.warning("Failed to delete previous base resume on disk")
        user.base_resume.filename = upload.filename
        user.base_resume.file_path = file_path
        user.base_resume.content_type = upload.content_type or ""
        user.base_resume.extracted_text = text
        user.base_resume.years_experience = resume_years
    else:
        db.add(BaseResume(
            user_id=user.id,
            filename=upload.filename,
            file_path=file_path,
            content_type=upload.content_type or "",
            extracted_text=text,
            years_experience=resume_years,
        ))
    # Invalidate any tailored resumes — they were built off the old base.
    db.query(TailoredResume).filter(TailoredResume.user_id == user.id).delete()
    db.commit()
    # Matching keys off resume-derived years now, so refresh the board right
    # away instead of waiting for the nightly rebuild.
    try:
        from .sync import rebuild_matches_for_user
        rebuild_matches_for_user(user.id)
    except Exception:
        logger.exception("Match rebuild after resume upload failed user_id=%d", user.id)
    if resume_years is not None:
        flash(
            f"Resume uploaded — we estimate about {resume_years} years of experience "
            "and matched your board to that level.",
            "success",
        )
    else:
        flash("Resume uploaded. Tailored versions are generated when you download them.", "success")
    return redirect(url_for("web.resume_page"))


@web.get("/resume/base")
def resume_download_base():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    db = get_db()
    user = db.get(User, user.id)
    if not user.base_resume or not os.path.exists(user.base_resume.file_path):
        abort(404)
    return send_file(
        user.base_resume.file_path,
        as_attachment=True,
        download_name=user.base_resume.filename or "resume",
    )


@web.route("/interview/<int:job_id>", methods=["GET", "POST"])
def interview_plan(job_id: int):
    """AI interview-prep plan for a job (Pro only). GET shows the stored plan
    or a generate CTA; POST generates it (once) and stores it."""
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    db = get_db()
    user = db.get(User, user.id)
    job = db.get(Job, job_id)
    if not job:
        abort(404)
    subscription = ensure_subscription(user, db)
    pro = is_pro(user, subscription)

    existing = db.query(InterviewPlan).filter(
        InterviewPlan.user_id == user.id, InterviewPlan.job_id == job_id
    ).one_or_none()

    def _current_shape(row) -> bool:
        # Plans stored before the 2026-07 restructure (14-day schedule format)
        # lack these sections — treat them as absent so they regenerate.
        try:
            return "company_background" in json.loads(row.content_json)
        except (TypeError, ValueError):
            return False

    if request.method == "POST":
        if not pro:
            flash("AI interview prep is a Pro feature. Upgrade to $19.99/mo to unlock it.", "error")
            return redirect(url_for("web.billing"))
        if existing is None or not _current_shape(existing):
            from .interview import generate_interview_plan
            resume_text = user.base_resume.extracted_text if user.base_resume else ""
            # Real salaries from the same market (city + vertical) ground the
            # salary-expectation band; the saved search's experience bucket is
            # the fallback when the resume doesn't reveal years of experience.
            market_jobs = db.query(Job).filter(
                Job.city == job.city, Job.vertical == job.vertical
            ).all()
            search = db.query(SavedSearch).filter(SavedSearch.user_id == user.id).first()
            plan = generate_interview_plan(
                job,
                resume_text,
                market_points=_salary_points_for(market_jobs),
                market_label=CITY_LABELS.get(job.city, job.location or job.city),
                fallback_bucket=effective_experience_bucket(db, search),
            )
            if not plan:
                flash("Couldn't build the interview plan right now. Please try again.", "error")
                return redirect(url_for("web.interview_plan", job_id=job_id))
            if existing is None:
                existing = InterviewPlan(user_id=user.id, job_id=job_id, content_json=json.dumps(plan))
                db.add(existing)
            else:
                existing.content_json = json.dumps(plan)
                existing.generated_at = utc_now()
            db.commit()
        return redirect(url_for("web.interview_plan", job_id=job_id))

    plan = json.loads(existing.content_json) if existing and _current_shape(existing) else None
    return render_template(
        "interview.html",
        user=user,
        job=job,
        plan=plan,
        is_pro=pro,
        generated_at=existing.generated_at if existing else None,
    )


@web.get("/resume/tailored/<int:job_id>")
def resume_download_tailored(job_id: int):
    """Serve the pre-generated tailored PDF.

    Tailored resumes are created by the daily sync (see app/sync.py) — this
    route never renders on demand, so the click always downloads instantly.
    """
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    db = get_db()
    user = db.get(User, user.id)
    job = db.get(Job, job_id)
    if not job:
        abort(404)
    tailored = db.query(TailoredResume).filter(
        TailoredResume.user_id == user.id,
        TailoredResume.job_id == job_id,
    ).one_or_none()
    already_built = bool(tailored and tailored.pdf_path and os.path.exists(tailored.pdf_path))
    if not already_built:
        # Creating a NEW tailored resume spends one AI-resume credit
        # (free = 10 lifetime, $4.99 = 25/mo, $19.99 = unlimited). Re-downloading
        # an already-built PDF is free.
        subscription = ensure_subscription(user, db)
        if not consume_resume_credit(subscription, city_limit_for(user, subscription)):
            flash(
                "You've used all your AI resume creations. Upgrade to $4.99/mo for "
                "25 a month, or $19.99/mo for unlimited.",
                "error",
            )
            return redirect(url_for("web.billing"))
        # Not pre-built — generate it on demand.
        base = user.base_resume if user else None
        if not base:
            abort(404)
        from .resumes import generate_tailored_resume
        try:
            pdf_path = generate_tailored_resume(
                user=user, job=job, base_resume=base, allow_fallback=True
            )
        except Exception:
            logger.exception("On-demand tailoring failed user=%s job=%s", user.id, job_id)
            abort(404)
        if not pdf_path:
            abort(404)
        if tailored:
            tailored.pdf_path = pdf_path
        else:
            tailored = TailoredResume(
                user_id=user.id, job_id=job_id, content_text="", pdf_path=pdf_path
            )
            db.add(tailored)
        db.commit()
    # Clicking "Tailored Resume" counts as applying. Two records get written:
    #   1. JobMatch.applied_at — drives the green "Applied" badge on the board.
    #   2. AppliedJob (record_application) — the durable, ~1-year history that
    #      survives the nightly rebuild and powers the Analytics page.
    # Both are idempotent: the first application wins the timestamp.
    for jm in db.query(JobMatch).filter(
        JobMatch.user_id == user.id,
        JobMatch.job_id == job_id,
    ).all():
        if jm.applied_at is None:
            jm.applied_at = utc_now()
    record_application(db, user.id, job)
    db.commit()
    parts = []
    for value in (job.company, job.title):
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
        cleaned = re.sub(r"-+", "-", cleaned)
        if cleaned:
            parts.append(cleaned)
    stem = "-".join(parts) or "resume"
    download_name = f"{stem[:120]}.pdf"
    return send_file(tailored.pdf_path, as_attachment=True, download_name=download_name)


@web.get("/applied")
def applied_history():
    """The Applied tab is retired — old bookmarks land on Analytics, which now
    carries the application history plus the all-users leaderboard."""
    return redirect(url_for("web.analytics"))


@web.get("/analytics")
def analytics():
    """Year-in-review: how many jobs the user applied to per week / month.

    Built off the durable AppliedJob history (app/applications.py), so it spans
    up to a year regardless of the 2-day board window or nightly rebuild.
    Also renders a leaderboard of every user's application counts.
    """
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    db = get_db()
    applications = applications_for_user(db, user.id)
    data = build_application_analytics(applications)
    # Outer join so users with zero applications still make the leaderboard.
    leaderboard_rows = db.execute(
        sa_select(User.id, User.email, AppliedJob.applied_at)
        .outerjoin(AppliedJob, AppliedJob.user_id == User.id)
    ).all()
    leaderboard = build_application_leaderboard(leaderboard_rows, current_user_id=user.id)
    return render_template(
        "analytics.html",
        user=user,
        summary=data["summary"],
        monthly=data["monthly"],
        weekly=data["weekly"],
        by_vertical=data["by_vertical"],
        by_city=data["by_city"],
        leaderboard=leaderboard,
    )


@web.get("/research")
def research():
    """Market value: what each market on the user's board pays, and what to ask
    for given their experience bucket."""
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    db = get_db()
    user = db.get(User, user.id)
    tabs = user_verticals(user)
    active_tab = request.args.get("tab", "")
    if active_tab not in tabs:
        active_tab = tabs[0]
    saved_search = user.saved_search_for(active_tab)
    cities = list(saved_search.cities) if saved_search else []
    experience_bucket = effective_experience_bucket(db, saved_search)
    data = build_market_research(
        db,
        cities,
        vertical=active_tab,
        experience_bucket=experience_bucket,
        user_id=user.id,
    )
    return render_template(
        "research.html",
        user=user,
        active_tab=active_tab,
        tab_labels=VERTICAL_LABELS,
        tab_order=tabs,
        saved_search=saved_search,
        markets=data["markets"],
        overall=data["overall"],
        applied_overall=data["applied_overall"],
        experience_label=data["experience_label"],
    )


FEEDBACK_MAX_LEN = 5000


@web.route("/feedback", methods=["GET", "POST"])
def feedback():
    """Open feedback form — any visitor (signed in or not) can leave a note,
    stored for the owner to review at /feedback/admin."""
    user = current_user()
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not message:
            flash("Please enter your feedback before sending.", "error")
            return redirect(url_for("web.feedback"))
        message = message[:FEEDBACK_MAX_LEN]
        email = request.form.get("email", "").strip().lower()
        if user and not email:
            email = user.email
        # Capture where they were so the owner has context; never trust it for
        # control flow — it's only display text and Jinja autoescapes it.
        page = (request.form.get("page", "").strip() or request.referrer or "")[:255]

        db = get_db()
        db.add(Feedback(
            user_id=user.id if user else None,
            email=email or None,
            message=message,
            page=page or None,
        ))
        db.commit()
        logger.info("Feedback submitted user_id=%s", user.id if user else None)
        flash("Thanks for the feedback — it's been sent to the team.", "success")
        return redirect(url_for("web.feedback"))

    return render_template("feedback.html", user=user)


@web.get("/feedback/admin")
def feedback_admin():
    """Owner-only inbox of submitted feedback. Returns 404 (not 403) for
    everyone else so the route's existence isn't disclosed."""
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    if not is_admin_email(user.email):
        abort(404)

    db = get_db()
    items = db.query(Feedback).order_by(Feedback.created_at.desc()).all()
    open_count = sum(1 for item in items if not item.is_resolved)
    return render_template(
        "feedback_admin.html",
        user=user,
        items=items,
        open_count=open_count,
        total=len(items),
    )


@web.post("/feedback/<int:feedback_id>/resolve")
def feedback_resolve(feedback_id: int):
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    if not is_admin_email(user.email):
        abort(404)

    db = get_db()
    item = db.get(Feedback, feedback_id)
    if not item:
        abort(404)
    item.is_resolved = not item.is_resolved
    db.commit()
    return redirect(url_for("web.feedback_admin"))


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
