#!/usr/bin/env python3
"""Backfill salary (and description) onto postings scraped before the vertical
scrapers learned to fetch them — see job_enrich.py.

Every non-PM track stored an empty description and no pay range, so a posting
that published "the pay range for this position is between $132,200.00 and
$220,400.00" showed no salary on the board. This re-fetches those postings and
re-parses them with the same code path the scrapers now use.

**It fixes the shared_jobs*.json feeds as well as the DB.** The feeds outrank
the DB — `run-daily-sync` re-upserts every posting from them — so a DB-only
repair is silently reverted on the next sync.

Usage:
  python scripts/backfill_salaries.py [--days 14] [--limit N] [--dry-run] [--all]
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.matching import PM_MIN_SALARY  # noqa: E402
from app.parsing import parse_experience_years  # noqa: E402
from job_enrich import (  # noqa: E402
    DESCRIPTION_MAX_CHARS,
    HEADERS,
    html_to_text,
    salary_fields,
    workday_detail_by_url,
)

DB_PATH = ROOT / "jordansjobfinder.db"
FEEDS = sorted(ROOT.glob("shared_jobs*.json"))

GREENHOUSE_URL = re.compile(
    r"^https://(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?P<token>[^/]+)/jobs/(?P<id>\d+)"
)


def workday_description(url: str) -> str:
    return workday_detail_by_url(url, timeout=20)["description"]


def greenhouse_description(url: str) -> str:
    m = GREENHOUSE_URL.match(url or "")
    if not m:
        return ""
    api = f"https://boards-api.greenhouse.io/v1/boards/{m['token']}/jobs/{m['id']}"
    try:
        resp = requests.get(api, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=20)
        if resp.status_code != 200:
            return ""
        return html_to_text(resp.json().get("content") or "")
    except Exception:
        return ""


def fetch_description(url: str) -> str:
    """The two platforms whose posting body is reachable from the URL alone.
    Company-hosted Greenhouse links (…?gh_jid=) carry no board token, and
    Oracle/Citi postings render client-side — those are left for the next
    scrape, which enriches at the source."""
    return workday_description(url) or greenhouse_description(url)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14,
                    help="only postings this recent (board window is 2-7 days)")
    ap.add_argument("--all", action="store_true", help="ignore --days")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import sqlite3

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    where = "salary_min IS NULL"
    params: list = []
    if not args.all:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).replace(tzinfo=None)
        where += " AND COALESCE(posted_at, found_at) >= ?"
        params.append(cutoff.isoformat(sep=" "))
    sql = (f"SELECT id, url, title, company, description, vertical FROM jobs "
           f"WHERE {where} ORDER BY id DESC")
    if args.limit:
        sql += f" LIMIT {args.limit}"
    rows = con.execute(sql, params).fetchall()
    print(f"{len(rows)} postings with no salary" + ("" if args.all else f" in the last {args.days} days"))

    updates: dict[str, dict] = {}   # url -> fields
    fetched = skipped = 0
    for index, row in enumerate(rows, 1):
        description = row["description"] or ""
        fields = salary_fields(description)
        if fields["salary_min"] is None:
            # A stored description is not proof the posting body was ever read.
            # The PM scraper stored the Workday page's JavaScript shell —
            # "Workday is currently unavailable. English العربية …" — which is
            # long, truthy, and has no pay in it, so trusting it meant every PM
            # posting stayed unrepairable. Re-fetch whenever the stored text
            # yields nothing; that is exactly the set being repaired.
            fresh = fetch_description(row["url"])
            time.sleep(0.15)
            if fresh:
                description, fields = fresh, salary_fields(fresh)
        if not description:
            skipped += 1
            continue
        fetched += 1
        if fields["salary_min"] is None:
            continue
        # PM postings under the track's floor keep their salary hidden, exactly
        # as scraper.py has always stored them. Publishing it would make the
        # job fail the PM salary gate and disappear from the board.
        note = f"→ {fields['salary_label']}"
        if row["vertical"] == "pm" and fields["salary_max"] < PM_MIN_SALARY:
            note = f"→ {fields['salary_label']} under the PM floor — not published"
            fields = {"salary_label": "", "salary_min": None, "salary_max": None}
        experience = parse_experience_years(row["title"] or "", description)
        updates[row["url"]] = {
            "description": description[:DESCRIPTION_MAX_CHARS],
            "experience_min": experience.min_years,
            "experience_max": experience.max_years,
            **fields,
        }
        print(f"  [{index}/{len(rows)}] {row['company']}: {row['title'][:60]} {note}")

    print(f"\nfetched {fetched}, unreachable {skipped}, salaries found {len(updates)}")
    if args.dry_run or not updates:
        return 0

    # DB first, then every feed that carries the URL.
    with con:
        for url, fields in updates.items():
            con.execute(
                """UPDATE jobs SET description = ?, salary_label = ?, salary_min = ?,
                          salary_max = ?,
                          experience_min = COALESCE(experience_min, ?),
                          experience_max = COALESCE(experience_max, ?)
                   WHERE url = ?""",
                (fields["description"], fields["salary_label"], fields["salary_min"],
                 fields["salary_max"], fields["experience_min"], fields["experience_max"], url),
            )
    print(f"updated {len(updates)} DB rows")

    for feed in FEEDS:
        try:
            jobs = json.loads(feed.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(jobs, list):
            continue
        touched = 0
        for job in jobs:
            fields = updates.get(job.get("url", ""))
            if not fields:
                continue
            job["description"] = fields["description"]
            job["salary_label"] = fields["salary_label"]
            job["salary_min"] = fields["salary_min"]
            job["salary_max"] = fields["salary_max"]
            if job.get("experience_min") is None:
                job["experience_min"] = fields["experience_min"]
            if job.get("experience_max") is None:
                job["experience_max"] = fields["experience_max"]
            touched += 1
        if touched:
            feed.write_text(json.dumps(jobs, indent=2))
            print(f"updated {touched} entries in {feed.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
