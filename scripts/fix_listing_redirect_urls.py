#!/usr/bin/env python3
"""Repair "View Role" links that open a board index instead of the posting.

`greenhouse_urls._verdict` used to accept any redirect that changed the path as
proof the company site had resolved the req. Stripe then renamed its board from
/jobs/search to /careers/search, so an UNPUBLISHED req started 302ing to a
different path that is still the 56-page role index — and every such job was
stored with a link to that index (2026-09-12: "Staff Product Manager,
Payments"). The verdict is fixed; this re-probes the URLs already on the board
under the corrected rule and rewrites the ones that were wrong.

Feeds before DB, as always: `run-daily-sync` re-upserts every posting from
shared_jobs*.json, so a DB-only rewrite is undone the next morning. And because
the upsert keys on URL, a rewritten row would otherwise be stranded alongside a
fresh one — the DB row is UPDATED in place so job_matches and applied history
follow it.

    python scripts/fix_listing_redirect_urls.py            # dry run
    python scripts/fix_listing_redirect_urls.py --apply
"""
import argparse
import json
import os
import sqlite3
import sys
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import greenhouse_urls
from greenhouse_urls import EMBED_URL

FEEDS = [
    "shared_jobs.json", "shared_jobs_finance.json", "shared_jobs_sales.json",
    "shared_jobs_it.json", "shared_jobs_hr.json", "shared_jobs_scm.json",
    "shared_jobs_project.json", "shared_jobs_analyst.json",
]
DB = "jordansjobfinder.db"


def token_map():
    """company label -> greenhouse board token, from every scraper's lists.

    The stored company is the LIST LABEL ("Stripe MIA"), not the token, and the
    embed URL needs the token. Importing the lists keeps this honest as they
    change rather than hardcoding a table that rots.
    """
    tokens = {}
    modules = [
        ("scraper", ["GREENHOUSE_COMPANIES", "GREENHOUSE_MULTI"]),
        ("scraper_finance", ["FINANCE_GREENHOUSE_COMPANIES"]),
        ("scraper_sales", ["SALES_GREENHOUSE_COMPANIES"]),
        ("scraper_it", ["IT_GREENHOUSE_COMPANIES"]),
        ("scraper_hr", ["HR_GREENHOUSE_COMPANIES"]),
        ("scraper_scm", ["SCM_GREENHOUSE_COMPANIES"]),
    ]
    for mod_name, names in modules:
        try:
            mod = __import__(mod_name)
        except Exception as exc:          # a scraper that won't import is not
            print(f"  ! {mod_name}: {exc}")   # a reason to skip the repair
            continue
        for name in names:
            for entry in getattr(mod, name, []) or []:
                if len(entry) >= 2:
                    tokens.setdefault(entry[0], entry[1])
    return tokens


def resolve(url, token):
    """The corrected verdict for one stored URL, or None to leave it alone."""
    # The id comes out of a STORED url here, not off the typed Greenhouse API
    # field, so it is attacker-adjacent text: a posting whose absolute_url
    # carried `gh_jid=<anything>` would otherwise be pasted straight into the
    # embed link we hand the user. Digits only.
    job_id = ""
    for part in urlsplit(url).query.split("&"):
        if part.startswith("gh_jid="):
            job_id = part[len("gh_jid="):]
    if not job_id.isdigit() or not token:
        return None
    parts = urlsplit(url)
    if parts.netloc.lower().endswith("greenhouse.io") or job_id in parts.path:
        return None
    embed = EMBED_URL.format(token=token, job_id=job_id)
    try:
        resp = greenhouse_urls.requests.head(
            url, headers={"User-Agent": greenhouse_urls._UA},
            timeout=greenhouse_urls._TIMEOUT, allow_redirects=True)
    except greenhouse_urls.requests.RequestException:
        return None                      # a blocked probe is not a dead posting
    if resp.status_code >= 400:
        return None
    fixed = greenhouse_urls._verdict(resp.url, parts.path, job_id, url, embed)
    return fixed if fixed != url else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    tokens = token_map()
    print(f"{len(tokens)} greenhouse tokens known")

    db = sqlite3.connect(DB)
    rows = [(i, c, t, u) for i, c, t, u in
            db.execute("select id, company, title, url from jobs")
            if u and "gh_jid=" in u]
    print(f"{len(rows)} board rows carry a gh_jid link")

    # One probe per distinct URL — the same req is on the board under several
    # city labels, and each probe is a request to someone else's site.
    replacements, untokened = {}, set()
    for _id, company, _title, url in rows:
        if url in replacements:
            continue
        token = tokens.get(company)
        if not token:
            untokened.add(company)
            continue
        fixed = resolve(url, token)
        if fixed:
            replacements[url] = fixed

    if untokened:
        print(f"no token for {len(untokened)} companies: "
              f"{', '.join(sorted(untokened)[:10])}")
    print(f"\n{len(replacements)} URLs now read as a board index:")
    for old, new in list(replacements.items())[:20]:
        print(f"  {old}\n   -> {new}")
    if not replacements:
        return
    if not args.apply:
        print("\n(dry run — pass --apply to write)")
        return

    for feed in FEEDS:                                  # feeds first
        if not os.path.exists(feed):
            continue
        entries = json.load(open(feed))
        changed = 0
        for entry in entries:
            new = replacements.get(entry.get("url"))
            if new:
                entry["url"] = new
                changed += 1
        if changed:
            json.dump(entries, open(feed, "w"))
            print(f"{feed}: {changed} rewritten")

    updated = collided = 0
    for old, new in replacements.items():
        existing = db.execute(
            "select id from jobs where url = ?", (new,)).fetchone()
        if existing:
            # The corrected URL is already on the board under another row;
            # drop the stranded one rather than violating jobs.url UNIQUE.
            for stale in db.execute(
                    "select id from jobs where url = ?", (old,)).fetchall():
                db.execute("delete from job_matches where job_id = ?", stale)
                db.execute("delete from tailored_resumes where job_id = ?", stale)
                db.execute("update applied_jobs set job_id = NULL "
                           "where job_id = ?", stale)
                db.execute("delete from jobs where id = ?", stale)
                collided += 1
        else:
            updated += db.execute(
                "update jobs set url = ? where url = ?", (new, old)).rowcount
    db.commit()
    print(f"db: {updated} rows repointed, {collided} duplicates removed")


if __name__ == "__main__":
    main()
