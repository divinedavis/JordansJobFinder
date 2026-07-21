import argparse

from app import create_app
from app.db import init_db
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
            "backfill-resume-years",
            "migrate-project-searches",
            "migrate-full-metro-coverage",
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

    if args.command == "backfill-resume-years":
        # One-time backfill: estimate years for resumes uploaded before the
        # years_experience column existed, then rebuild matches so boards
        # reflect resume-derived seniority immediately.
        from app.db import get_db
        from app.experience import estimate_resume_years
        from app.models import BaseResume

        with app.app_context():
            db = get_db()
            updated = 0
            for resume in db.query(BaseResume).all():
                years = estimate_resume_years(resume.extracted_text)
                if resume.years_experience != years:
                    resume.years_experience = years
                    updated += 1
            db.commit()
            matched = rebuild_matches()
        print(f"Backfilled years on {updated} resumes; rebuilt {matched} matches.")
        return

    if args.command == "migrate-project-searches":
        # 2026-07-19: project management merged into the Product/Program
        # Manager board. Convert standalone project saved searches to the PM
        # track (keeping cities); drop them when the user already has a PM
        # search, then rebuild matches.
        from app.db import get_db
        from app.models import SavedSearch

        with app.app_context():
            db = get_db()
            converted = dropped = 0
            for search in db.query(SavedSearch).filter(SavedSearch.vertical == "project").all():
                has_pm = (
                    db.query(SavedSearch)
                    .filter(SavedSearch.user_id == search.user_id, SavedSearch.vertical == "pm")
                    .count()
                )
                if has_pm:
                    db.delete(search)
                    dropped += 1
                else:
                    search.vertical = "pm"
                    search.title_slug = "technical-product-manager"
                    converted += 1
            db.commit()
            matched = rebuild_matches()
        print(f"Converted {converted}, dropped {dropped} project searches; rebuilt {matched} matches.")
        return

    if args.command == "migrate-full-metro-coverage":
        # 2026-07-21: the city picker is gone and every board covers every
        # metro. New searches are seeded with the full set, but rows written
        # before today still carry whatever the old picker (and the free
        # tier's 3-city cap) left them with — so without this, existing users
        # keep seeing 3 or 4 metros while the code believes they see 29.
        from app.catalog import ALL_CITY_LABELS
        from app.db import get_db
        from app.models import SavedSearch

        full = list(ALL_CITY_LABELS)
        with app.app_context():
            db = get_db()
            widened = 0
            for search in db.query(SavedSearch).all():
                if list(search.cities or []) != full:
                    search.cities = list(full)
                    search.is_paid_city_override = False
                    widened += 1
            db.commit()
            matched = rebuild_matches()
        print(f"Widened {widened} saved searches to all {len(full)} metros; "
              f"rebuilt {matched} matches.")
        return

    if args.command == "run-daily-sync":
        with app.app_context():
            result = run_daily_sync()
        print(
            f"Completed daily sync. Shared jobs: {result['synced_jobs']}; "
            f"job matches: {result['matched_jobs']}."
        )
        return

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
