#!/usr/bin/env python
"""Take postings the employer has removed off the board.

Nothing ever asked whether a stored req still exists. The board's only test was
the posting date, so a job pulled the day after it was scraped sat there until
its date aged out and "View Role" opened a 404. scraper.py now sweeps its store
every run (`drop_removed_postings`); this repairs what is already stored.

Only Workday removals are detectable from the URL alone, and only a 404 counts:
a WAF 403 (Morgan Stanley blocks the droplet's whole range) or a timeout must
never delete a live posting.

**Feeds before DB** — run-daily-sync re-upserts every posting from
shared_jobs*.json, so a DB-only delete comes back on the next sync. The durable
application history is kept: applied_jobs.job_id is NULLed, never deleted.

    python scripts/prune_removed_postings.py [--days 7] [--dry-run]
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from job_enrich import workday_posting_removed  # noqa: E402

DB_PATH = REPO_ROOT / "jordansjobfinder.db"
FEEDS = sorted(REPO_ROOT.glob("shared_jobs*.json"))
STORE = REPO_ROOT / "jobs_store.json"


def candidates(days):
    """Board-visible postings worth probing, newest first."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    rows = con.execute(
        "SELECT id, url, company, title FROM jobs"
        " WHERE url LIKE '%myworkdayjobs.com%'"
        "   AND COALESCE(posted_at, found_at) >= ?"
        " ORDER BY COALESCE(posted_at, found_at) DESC",
        (cutoff.isoformat(sep=" "),),
    ).fetchall()
    con.close()
    return rows


def prune_json(path, dead_urls, dry_run):
    try:
        rows = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(rows, list):
        return 0
    kept = [row for row in rows if row.get("url") not in dead_urls]
    dropped = len(rows) - len(kept)
    if dropped and not dry_run:
        path.write_text(json.dumps(kept, indent=2))
    if dropped:
        print(f"  {path.name}: dropped {dropped}")
    return dropped


def prune_db(dead_ids, dry_run):
    con = sqlite3.connect(DB_PATH)
    marks = ",".join("?" * len(dead_ids))
    with con:
        if not dry_run:
            # applied_jobs is durable history — the FK is ON DELETE SET NULL and
            # raw sqlite3 does not enforce it (PRAGMA foreign_keys defaults OFF),
            # so unlink by hand before the job rows go.
            con.execute(f"UPDATE applied_jobs SET job_id = NULL WHERE job_id IN ({marks})", dead_ids)
            con.execute(f"DELETE FROM job_matches WHERE job_id IN ({marks})", dead_ids)
            con.execute(f"DELETE FROM tailored_resumes WHERE job_id IN ({marks})", dead_ids)
            con.execute(f"DELETE FROM jobs WHERE id IN ({marks})", dead_ids)
    con.close()
    print(f"  jobs table: removed {len(dead_ids)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="how far back to probe")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print("DRY RUN — nothing is written\n")

    rows = candidates(args.days)
    print(f"probing {len(rows)} Workday postings from the last {args.days} days")
    dead_ids, dead_urls = [], set()
    for row in rows:
        if workday_posting_removed(row["url"]):
            dead_ids.append(row["id"])
            dead_urls.add(row["url"])
            print(f"  removed by employer: {row['company']} — {row['title'][:52]}")
        time.sleep(0.15)

    print(f"\n{len(dead_ids)} removed posting(s)")
    if not dead_ids:
        return
    print("\nFeeds (these outrank the DB):")
    for feed in FEEDS + [STORE]:
        prune_json(feed, dead_urls, args.dry_run)
    print("\nDatabase:")
    if not args.dry_run:
        prune_db(dead_ids, args.dry_run)


if __name__ == "__main__":
    main()
