from flask import Flask
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

    app.register_blueprint(web)

    csrf.exempt("web.stripe_webhook")

    # Fix #4: Rate limit auth endpoints
    for endpoint in ("sign_in", "login"):
        view_func = app.view_functions.get(f"web.{endpoint}")
        if view_func:
            app.view_functions[f"web.{endpoint}"] = limiter.limit("8/minute")(view_func)

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
            "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://cdn.undraw.co; "
            "connect-src 'self' https://challenges.cloudflare.com; "
            "frame-src https://challenges.cloudflare.com https://js.stripe.com; "
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
            f"job matches: {result['matched_jobs']}."
        )

    return app
