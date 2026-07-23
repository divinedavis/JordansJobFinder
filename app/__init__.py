import secrets
from pathlib import Path

from flask import Flask, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .db import close_db_session, init_db
from .routes import web
from .sync import rebuild_matches, run_daily_sync, upsert_shared_jobs

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    # Fix #2: ProxyFix so remote_addr reflects the real client IP behind nginx
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    csrf.init_app(app)
    limiter.init_app(app)

    # Ensure resume storage dirs exist and are owned by the running process.
    # Avoids PermissionError when the dirs were created by a different user
    # (e.g. as root during manual init-db).
    for cfg_key in ("RESUME_UPLOAD_DIR", "RESUME_TAILORED_DIR"):
        try:
            Path(app.config[cfg_key]).mkdir(parents=True, exist_ok=True)
        except OSError:
            app.logger.warning("Could not create resume dir %s", app.config[cfg_key])

    # Fail-closed Turnstile: in production we intend bot protection to be
    # enforced. If the secret is missing there, log loudly — the auth routes
    # will reject signup/login (they fail closed) until it's configured.
    if app.config.get("TURNSTILE_REQUIRED") and not app.config.get("TURNSTILE_SECRET_KEY"):
        app.logger.warning(
            "TURNSTILE_SECRET_KEY is unset in a PRODUCTION config. Bot protection "
            "fails CLOSED: signup and login will be rejected until the secret is "
            "set. Configure TURNSTILE_SECRET_KEY in the production env."
        )

    app.register_blueprint(web)

    csrf.exempt("web.stripe_webhook")

    # Fix #4: Rate limit auth + expensive endpoints. Auth limits slow brute
    # force; the resume routes guard the Anthropic API spend (each cache-miss
    # tailored download is a paid LLM call) and the PDF/DOCX parse cost.
    route_limits = {
        "sign_in": ("8/minute", None),
        "login": ("8/minute", None),
        "resume_download_tailored": ("30/hour", None),
        "resume_upload": ("10/hour", None),
        # Fix #12 (OWASP LLM10 — unbounded LLM cost): each interview-plan POST is
        # a paid Anthropic call, is_pro() is now open to everyone, and no credit
        # is consumed — so a signed-in user could enumerate job_ids and trigger
        # unlimited spend under the loose global default. Limit the POST that
        # generates the plan to the same 30/hour the tailored-resume LLM path
        # uses; GET (viewing the cached plan) is unaffected.
        "interview_plan": ("30/hour", ["POST"]),
        "feedback": ("10/hour", ["POST"]),
    }
    for endpoint, (limit, methods) in route_limits.items():
        view_func = app.view_functions.get(f"web.{endpoint}")
        if view_func:
            app.view_functions[f"web.{endpoint}"] = limiter.limit(
                limit, methods=methods
            )(view_func)

    @app.before_request
    def _set_csp_nonce():
        # Per-request nonce so the inline Google-tag init script can run under a
        # strict CSP (no 'unsafe-inline'). Exposed to templates via context
        # processor as `csp_nonce`.
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_csp_nonce():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        # Fix #5: Content-Security-Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' https://challenges.cloudflare.com "
            f"https://www.googletagmanager.com 'nonce-{g.get('csp_nonce', '')}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://cdn.undraw.co https://www.google.com "
            "https://googleads.g.doubleclick.net; "
            "connect-src 'self' https://challenges.cloudflare.com "
            "https://www.googletagmanager.com https://www.google.com "
            "https://googleads.g.doubleclick.net; "
            "frame-src https://challenges.cloudflare.com https://js.stripe.com "
            "https://td.doubleclick.net; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://checkout.stripe.com"
        )
        return response

    @app.teardown_appcontext
    def shutdown_session(_exception=None):
        close_db_session()

    @app.cli.command("init-db")
    def init_db_command():
        init_db()
        print("Initialized database.")

    @app.cli.command("sync-shared-jobs")
    def sync_shared_jobs_command():
        count = upsert_shared_jobs()
        print(f"Synced {count} shared jobs.")

    @app.cli.command("rebuild-matches")
    def rebuild_matches_command():
        count = rebuild_matches()
        print(f"Created {count} job matches.")

    @app.cli.command("run-daily-sync")
    def run_daily_sync_command():
        result = run_daily_sync()
        print(
            f"Completed daily sync. Shared jobs: {result['synced_jobs']}; "
            f"job matches: {result['matched_jobs']}; "
            f"tailored resumes: {result.get('tailored_resumes', 0)}."
        )

    return app
