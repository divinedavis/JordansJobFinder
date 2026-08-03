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

**Relative labels resolve against the posting's discovery time, not now.**
Resolving "Posted Today" against now re-dates the posting to today every time
this runs, which is the bug rather than the repair: it stamped a Morgan Stanley
req first seen 2026-03-23 as posted 2026-08-02 and put it back on the board.
found_at is when the label was read, so it's the honest anchor.

**A row still carried by a feed is left alone.** A vertical scraper rewrites its
feed every run, so a job in one was re-read today and its date belongs to the
scrape, not to first discovery — a posting really can be reposted months after
we first saw it. Only orphans (nothing left to refresh them) are re-anchored,
and only when their date is impossible: posted *after* the day we found them.

    python scripts/backfill_posted_dates.py [--dry-run]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import create_app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.models import Job  # noqa: E402
from posted_dates import parse_relative_posted  # noqa: E402
from sqlalchemy import select  # noqa: E402

FEEDS = sorted(REPO_ROOT.glob("shared_jobs*.json"))

RELATIVE = ("today", "yesterday", "ago", "just posted", "moments")


def _is_relative(label):
    text = (label or "").lower()
    return any(token in text for token in RELATIVE)


def _anchor(value):
    """The moment the label was read, as an aware datetime, or None."""
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _feed_rows(path):
    try:
        rows = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"  {path.name}: unreadable ({e}) — skipped")
        return None
    return rows if isinstance(rows, list) else None


def feed_urls():
    urls = set()
    for path in FEEDS:
        for row in _feed_rows(path) or []:
            if row.get("url"):
                urls.add(row["url"])
    return urls


def backfill_feeds(dry_run):
    total = 0
    for path in FEEDS:
        rows = _feed_rows(path)
        if rows is None:
            continue
        changed = 0
        for row in rows:
            if row.get("posted_at"):
                continue
            anchor = _anchor(row.get("found_at"))
            parsed = parse_relative_posted(row.get("posted_label") or "", now=anchor)
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
    live = feed_urls()
    app = create_app()
    with app.app_context():
        db = get_db()
        jobs = db.execute(select(Job)).scalars().all()
        missing = [job for job in jobs if job.posted_at is None]
        # An orphan whose relative label resolved to a date AFTER the day it was
        # discovered: nothing can post a job later than the run that read
        # "Posted Today" off it, so the date came from re-resolving a frozen
        # label against a later clock.
        drifted = [
            job for job in jobs
            if job.posted_at is not None
            and job.found_at is not None
            and job.url not in live
            and _is_relative(job.posted_label)
            and job.posted_at > job.found_at + timedelta(days=1)
        ]
        changed = 0
        stale = 0
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
        for job in missing + drifted:
            anchor = _anchor(job.found_at)
            parsed = parse_relative_posted(job.posted_label or "", now=anchor)
            if parsed is None:
                continue
            # SQLite stores naive datetimes — never write an aware one.
            job.posted_at = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            job.posted_label = job.posted_at.strftime("%Y-%m-%d")
            changed += 1
            if (cutoff - job.posted_at).days > 2:
                stale += 1
                print(f"    ages off: {job.company} — {job.title[:48]} ({job.posted_label})")
        if not dry_run:
            db.commit()
        print(f"  jobs table: {len(missing)} undated + {len(drifted)} re-dated orphan(s);"
              f" {changed} repaired, {stale} now age off the board")
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
