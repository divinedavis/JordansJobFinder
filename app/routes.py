import logging
import os
import re

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
    FINANCE_DEFAULT_CITIES,
    SALES_DEFAULT_CITIES,
    TITLE_LABELS,
    TITLE_VERTICALS,
    VERTICAL_DEFAULT_CITIES,
    city_choices,
    experience_choices,
    title_choices,
)
from .db import get_db
from .matching import choose_cities, city_from_slug, is_admin_email, is_superuser_email
from .models import AppliedJob, BaseResume, Feedback, Job, JobMatch, SavedSearch, Subscription, TailoredResume, User
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
    create_checkout_session,
    handle_webhook_event,
    stripe_configured,
    sync_checkout_result,
)
from .results import group_matches_by_city, home_board_preview, load_db_matches, preview_matches
from .applications import applications_for_user, record_application
from .analytics import (
    build_application_analytics,
    build_application_leaderboard,
    build_market_research,
)
from .searches import (
    can_change_search,
    requires_paid_city_override,
    revert_to_free_cities,
    valid_experience_bucket,
    valid_title_slug,
    validate_saved_search,
)
from .security import (
    account_locked,
    clear_failed_logins,
    enforce_turnstile,
    hash_identifier,
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

        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
        ensure_subscription(user, db)
        user.set_password(password)
        # Open access: seed every new user with all 6 metros so they land on a
        # populated board immediately. title_slug + experience_bucket are
        # required by the schema but ignored by the superuser matching branch.
        db.add(SavedSearch(
            user_id=user.id,
            vertical="pm",
            title_slug="technical-product-manager",
            experience_bucket="7-9",
            cities=[
                "New York, NY",
                "Atlanta, GA",
                "Miami, FL",
                "Dallas, TX",
                "Houston, TX",
                "Washington, DC",
                "Los Angeles, CA",
            ],
            is_paid_city_override=False,
        ))
        db.add(SavedSearch(
            user_id=user.id,
            vertical="finance",
            title_slug="entry-finance-any",
            experience_bucket="0-2",
            cities=list(FINANCE_DEFAULT_CITIES),
            is_paid_city_override=False,
        ))
        db.add(SavedSearch(
            user_id=user.id,
            vertical="sales",
            title_slug="entry-sales-any",
            experience_bucket="0-2",
            cities=list(SALES_DEFAULT_CITIES),
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
    "pm": "Product/Program Manager",
    "finance": "Entry Finance",
    "sales": "Entry Sales",
    "it": "IT Project/Program Manager",
    "hr": "HR Coordinator+",
}
VERTICAL_ORDER = ["pm", "finance", "sales", "it", "hr"]


def user_verticals(user) -> list[str]:
    """Tabs are personal: a user only sees the verticals they have a saved
    search for (e.g. an IT-track user sees just the IT tab — no finance/sales)."""
    tabs = [v for v in VERTICAL_ORDER if user.saved_search_for(v)]
    return tabs or ["pm"]


# Tracks a user can add themselves with one click from the tab row. Only the
# opt-in tracks are offered (finance/sales are seeded at signup and some users
# intentionally have them removed — don't resurface those as buttons).
ADDABLE_TRACKS = [
    {"vertical": "hr", "title_slug": "hr-coordinator", "experience_bucket": "7-9"},
]


def addable_tracks_for(user) -> list[dict]:
    return [
        {**track, "label": VERTICAL_LABELS[track["vertical"]]}
        for track in ADDABLE_TRACKS
        if not user.saved_search_for(track["vertical"])
    ]


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
        addable_tracks=addable_tracks_for(user),
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

        # Non-PM titles (finance/sales/IT/HR) select a whole track: the
        # vertical's search is created/updated with its pinned city set (the
        # 3-city picker below is PM-specific) and its tab appears on the
        # dashboard immediately.
        vertical = TITLE_VERTICALS.get(title_slug, "pm")
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
            search.cities = list(VERTICAL_DEFAULT_CITIES[vertical])
            search.is_paid_city_override = False
            db.commit()
            try:
                from .sync import rebuild_matches_for_user
                rebuild_matches_for_user(user.id)
            except Exception:
                logger.exception("Match rebuild after track add failed user_id=%d", user.id)
            flash(f"{TITLE_LABELS.get(title_slug, title_slug)} added to your dashboard.", "success")
            return redirect(url_for("web.dashboard", tab=vertical))

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
            search = SavedSearch(user_id=user.id, vertical="pm")
            db.add(search)

        is_paid_city_override = requires_paid_city_override(selected_cities, user.email)
        if is_paid_city_override and not subscription.city_override_active:
            flash("Custom cities require the $2.99 monthly city plan.", "error")
            return redirect(url_for("web.saved_search"))

        search.title_slug = title_slug
        search.experience_bucket = experience_bucket
        search.cities = list(selected_cities)
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


@web.get("/resume")
def resume_page():
    user = require_user()
    if not user:
        return redirect(url_for("web.sign_in"))
    db = get_db()
    user = db.get(User, user.id)
    return render_template("resume.html", user=user, base_resume=user.base_resume)


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
    else:
        db.add(BaseResume(
            user_id=user.id,
            filename=upload.filename,
            file_path=file_path,
            content_type=upload.content_type or "",
            extracted_text=text,
        ))
    # Invalidate any tailored resumes — they were built off the old base.
    db.query(TailoredResume).filter(TailoredResume.user_id == user.id).delete()
    db.commit()
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
    if not tailored or not tailored.pdf_path or not os.path.exists(tailored.pdf_path):
        # Not pre-built by the nightly sync — generate it on demand so a user who
        # just signed up / uploaded a resume still gets a tailored PDF instantly.
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
    leaderboard = build_application_leaderboard(leaderboard_rows)
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
    experience_bucket = saved_search.experience_bucket if saved_search else None
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
