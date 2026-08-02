#!/usr/bin/env python
"""Backfill posted_at for postings stored before the relative-date parser fix.

scraper.py couldn't parse Workday's relative labels ("Posted 30+ Days Ago"), so
those postings were stored with posted_at NULL. Every recency check then fell
back to found_at — first *discovery* time, which resets whenever the job is
rediscovered — so a months-old posting stayed on the board forever.

Resolving posted_at from the label is what ages them off: the dashboard's
window and purge_old_store both prefer posted_at when it exists.

**Fixes the shared_jobs*.json feeds as well as the DB.** run-daily-sync
re-upserts every posting from those files, so a DB-only repair is reverted on
the next sync.

Note the resolved date is relative to *now*, not to when the label was scraped,
so it's the youngest the posting can be — which errs toward keeping a job on
the board rather than deleting one that's still live.

    python scripts/backfill_posted_dates.py [--dry-run]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import create_app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.models import Job  # noqa: E402
from posted_dates import parse_relative_posted  # noqa: E402
from sqlalchemy import select  # noqa: E402

FEEDS = sorted(REPO_ROOT.glob("shared_jobs*.json"))


def backfill_feeds(dry_run):
    total = 0
    for path in FEEDS:
        try:
            rows = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"  {path.name}: unreadable ({e}) — skipped")
            continue
        if not isinstance(rows, list):
            continue
        changed = 0
        for row in rows:
            if row.get("posted_at"):
                continue
            parsed = parse_relative_posted(row.get("posted_label") or "")
            if parsed is None:
                continue
            row["posted_at"] = parsed.isoformat()
            changed += 1
        if changed and not dry_run:
            path.write_text(json.dumps(rows, indent=2))
        print(f"  {path.name}: {changed} of {len(rows)} backfilled")
        total += changed
    return total


def backfill_db(dry_run):
    app = create_app()
    with app.app_context():
        db = get_db()
        rows = db.execute(select(Job).where(Job.posted_at.is_(None))).scalars().all()
        changed = 0
        stale = 0
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
        for job in rows:
            parsed = parse_relative_posted(job.posted_label or "")
            if parsed is None:
                continue
            # SQLite stores naive datetimes — never write an aware one.
            job.posted_at = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            changed += 1
            if (cutoff - job.posted_at).days > 2:
                stale += 1
                print(f"    ages off: {job.company} — {job.title[:48]} ({job.posted_label})")
        if not dry_run:
            db.commit()
        print(f"  jobs table: {changed} of {len(rows)} NULL rows backfilled; {stale} now age off the board")
        return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print("DRY RUN — nothing is written\n")
    print("Feeds (these outrank the DB):")
    backfill_feeds(args.dry_run)
    print("\nDatabase:")
    backfill_db(args.dry_run)


if __name__ == "__main__":
    main()
