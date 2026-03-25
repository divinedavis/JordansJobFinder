import argparse

from app import create_app
from app.db import init_db
from app.devtools import seed_demo_user
from app.sync import rebuild_matches, run_daily_sync, upsert_shared_jobs


app = create_app()


def main():
    parser = argparse.ArgumentParser(description="Jordan's Job Finder app runner")
    parser.add_argument(
        "command",
        nargs="?",
        default="runserver",
        choices=[
            "runserver",
            "init-db",
            "sync-shared-jobs",
            "rebuild-matches",
            "run-daily-sync",
            "seed-demo",
        ],
        help="Command to execute",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.command == "init-db":
        with app.app_context():
            init_db()
        print("Initialized database.")
        return

    if args.command == "sync-shared-jobs":
        with app.app_context():
            count = upsert_shared_jobs()
        print(f"Synced {count} shared jobs.")
        return

    if args.command == "rebuild-matches":
        with app.app_context():
            count = rebuild_matches()
        print(f"Created {count} job matches.")
        return

    if args.command == "run-daily-sync":
        with app.app_context():
            result = run_daily_sync()
        print(
            f"Completed daily sync. Shared jobs: {result['synced_jobs']}; "
            f"job matches: {result['matched_jobs']}."
        )
        return

    if args.command == "seed-demo":
        with app.app_context():
            result = seed_demo_user()
        print(f"Seeded demo user: {result['email']}")
        return

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
