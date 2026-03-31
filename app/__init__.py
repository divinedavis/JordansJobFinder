from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from .config import Config
from .db import close_db_session, init_db
from .routes import web
from .sync import rebuild_matches, run_daily_sync, upsert_shared_jobs

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    csrf.init_app(app)
    limiter.init_app(app)

    app.register_blueprint(web)

    csrf.exempt("web.stripe_webhook")

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
