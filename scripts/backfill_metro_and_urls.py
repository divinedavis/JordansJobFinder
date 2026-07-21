"""One-off backfill for the 2026-07-21 decoy-metro + Greenhouse-deep-link fixes.

Both bugs baked their bad value into the posting at scrape time, so fixing the
scrapers only helps postings found from the next run onward. This rewrites what
is already on the board:

1. **city** — postings whose stored metro was only matched through a decoy place
   name (Skechers' "Manhattan Beach, CA" filed under nyc). Re-inferred with the
   vertical's own matcher, since the verticals cover different metro sets. A
   posting the vertical can't place at all is dropped — it isn't in a supported
   metro, so it should never have reached the board.
2. **url** — postings still pointing at a `?gh_jid=` search page that doesn't
   deep-link, rewritten to the Greenhouse-hosted application page.

**The shared_jobs*.json feeds are the source of truth, so they get fixed first.**
Editing only the DB is pointless: the next `run-daily-sync` re-upserts every
posting from those files and overwrites the correction (learned the hard way —
the first pass fixed two Skechers rows and the resync immediately undid them).
Rewriting a URL also strands the old row, so those are deleted rather than left
to show up as a duplicate card until they age out.

Idempotent; run again safely. Pass --apply to write, otherwise it dry-runs.
Follow with `manage.py run-daily-sync`.
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from greenhouse_urls import greenhouse_job_url  # noqa: E402
from metros import infer_metro, matches_metro  # noqa: E402

DB = ROOT / "jordansjobfinder.db"

# shared_jobs.json is the PM feed; the rest are suffixed with their vertical.
FEEDS = {
    "shared_jobs.json": "pm",
    "shared_jobs_finance.json": "finance",
    "shared_jobs_sales.json": "sales",
    "shared_jobs_it.json": "it",
    "shared_jobs_hr.json": "hr",
    "shared_jobs_scm.json": "scm",
    "shared_jobs_project.json": "project",
    "shared_jobs_analyst.json": "analyst",
}


def _vertical_matchers():
    """vertical -> callable(location) -> city slug ("" when unsupported)."""
    import scraper
    import scraper_finance
    import scraper_hr
    import scraper_it
    import scraper_sales
    import scraper_scm

    def pm(loc):
        return scraper.infer_pm_city(loc) or ""

    return {
        "pm": pm,
        "project": pm,
        "it": scraper_it.infer_city,
        "hr": scraper_hr.infer_city,
        "finance": scraper_finance.infer_city,
        "sales": scraper_sales.infer_city,
        "scm": scraper_scm.infer_city,
        "analyst": scraper_scm.infer_city,
    }


def _greenhouse_tokens():
    """company name -> greenhouse board token, read from the scraper configs."""
    tokens = {}
    for name in ("scraper.py", "scraper_finance.py", "scraper_sales.py",
                 "scraper_it.py", "scraper_hr.py", "scraper_scm.py",
                 "scraper_sc_employers.py"):
        text = (ROOT / name).read_text()
        for company, token in re.findall(r'\("([^"]+)",\s*"([a-z0-9_.-]+)"', text):
            tokens.setdefault(company, token)
            # Employer lists carry city-suffixed variants ("Stripe MIA").
            tokens.setdefault(re.sub(r"\s+[A-Z]{2,3}$", "", company), token)
    return tokens


def resolve_url(company, url, tokens):
    """New URL for a posting, or the same URL when nothing needs changing."""
    if not url or "gh_jid=" not in url:
        return url
    if urlsplit(url).netloc.lower().endswith("greenhouse.io"):
        return url  # already the hosted page
    base = re.sub(r"\s+[A-Z]{2,3}$", "", company or "")
    token = tokens.get(company) or tokens.get(base)
    gh_jid = re.search(r"gh_jid=(\d+)", url)
    if not token or not gh_jid:
        return url
    return greenhouse_job_url({"id": int(gh_jid.group(1)), "absolute_url": url}, token)


def resolve_city(location, city, vertical, matchers):
    """(new_city, changed). new_city of "" means the posting should be dropped.

    The test is whether the location still SUPPORTS the stored metro, not
    whether inference would pick the same one. That distinction matters for
    multi-office postings: "Menlo Park, CA; New York, NY" stored as nyc is
    correct and must be left alone, even though inference alone would answer
    san-francisco (MATCH_ORDER decides, and it puts SF first). Re-inferring
    those wholesale moved a pile of legitimate NYC jobs to San Francisco.

    So: leave anything the location still supports; only re-infer the rows it
    doesn't — Xcel Energy's "Lubbock, TX" sitting on the Dallas board.
    """
    if not location:
        return city, False
    if matches_metro(location, city):
        return city, False
    new_city = infer_metro(location)
    return new_city, new_city != city


def fix_feeds(apply, matchers, tokens):
    """Returns {old_url: new_url} and the count of city fixes / drops."""
    url_map, city_fixes, drops = {}, 0, 0

    for filename, vertical in FEEDS.items():
        path = ROOT / filename
        if not path.exists():
            continue
        entries = json.loads(path.read_text())
        kept, dirty = [], False

        for job in entries:
            company, url = job.get("company", ""), job.get("url", "")
            new_url = resolve_url(company, url, tokens)
            if new_url != url:
                url_map[url] = new_url
                job["url"] = new_url
                dirty = True
                print(f"  url   [{filename}] {company:<16} {job.get('title','')[:34]}")

            new_city, changed = resolve_city(
                job.get("location", ""), job.get("city", ""), vertical, matchers)
            if changed:
                dirty = True
                if not new_city:
                    drops += 1
                    print(f"  drop  [{filename}] {company:<16} "
                          f"{job.get('location','')} — no supported metro")
                    continue
                city_fixes += 1
                print(f"  city  [{filename}] {company:<16} "
                      f"{job.get('location',''):<24} {job.get('city')} -> {new_city}")
                job["city"] = new_city
            kept.append(job)

        if dirty and apply:
            path.write_text(json.dumps(kept, indent=2))

    return url_map, city_fixes, drops


def fix_db(conn, apply, url_map, matchers):
    """Mirror the feed fixes into jobs rows so the board is right before the
    next sync, and clear rows stranded by a URL rewrite."""
    updated = deleted = 0

    for old_url, new_url in url_map.items():
        row = conn.execute("select id from jobs where url = ?", (old_url,)).fetchone()
        if not row:
            continue
        clash = conn.execute("select id from jobs where url = ?", (new_url,)).fetchone()
        if clash:
            # The corrected posting already landed — drop the stale duplicate
            # so the dashboard doesn't show the same role twice.
            if apply:
                conn.execute("delete from job_matches where job_id = ?", (row[0],))
                conn.execute("delete from jobs where id = ?", (row[0],))
            deleted += 1
        else:
            if apply:
                conn.execute("update jobs set url = ? where id = ?", (new_url, row[0]))
            updated += 1

    rows = conn.execute(
        "select id, company, location, city, vertical from jobs "
        "where location is not null and location != ''"
    ).fetchall()
    city_fixes = dropped = 0
    for job_id, company, location, city, vertical in rows:
        new_city, changed = resolve_city(location, city, vertical, matchers)
        if not changed:
            continue
        if new_city:
            city_fixes += 1
            print(f"  db    {company:<18} {location:<26} {city} -> {new_city}")
            if apply:
                conn.execute("update jobs set city = ? where id = ?", (new_city, job_id))
        else:
            dropped += 1
            print(f"  db    {company:<18} {location:<26} {city} -> (dropped)")
            if apply:
                conn.execute("delete from job_matches where job_id = ?", (job_id,))
                conn.execute("delete from jobs where id = ?", (job_id,))
    return updated, deleted, city_fixes, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes")
    args = ap.parse_args()

    matchers, tokens = _vertical_matchers(), _greenhouse_tokens()

    print("== feeds (source of truth) ==")
    url_map, feed_cities, feed_drops = fix_feeds(args.apply, matchers, tokens)

    print("== jobs table ==")
    conn = sqlite3.connect(DB)
    updated, deleted, db_cities, db_drops = fix_db(conn, args.apply, url_map, matchers)

    verb = "applied" if args.apply else "would apply"
    print(f"\n{verb}: {len(url_map)} feed url rewrites, {feed_cities} feed city fixes, "
          f"{feed_drops} feed drops")
    print(f"{'':>8} {updated} db url updates, {deleted} stale duplicates removed, "
          f"{db_cities} db city fixes, {db_drops} db drops")

    if args.apply:
        conn.commit()
        print("\nnow run: manage.py run-daily-sync")
    else:
        print("\n(dry run — pass --apply)")


if __name__ == "__main__":
    main()
