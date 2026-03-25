from flask import Flask

from .config import Config
from .db import close_db_session, init_db
from .routes import web
from .sync import rebuild_matches, run_daily_sync, upsert_shared_jobs


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    app.register_blueprint(web)

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
