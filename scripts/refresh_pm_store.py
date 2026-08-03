#!/usr/bin/env python
"""Re-apply the PM store's own rules to jobs_store.json without a 40-minute scrape.

The store is the PM track's durable set of live postings and the feed is built
from it, so a store carrying bad data keeps producing bad boards until the next
nightly run. This runs the same steps scraper.main() ends with:

  re-enrich → freeze relative labels → purge by date → drop removed → save feed

Re-enrichment matters because the postings in the store were read off Workday's
JavaScript shell: their stored description is "Workday is currently
unavailable. English العربية …" and their salary is the "See posting"
placeholder the board renders as nothing.

    python scripts/refresh_pm_store.py [--dry-run]
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scraper  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    store = scraper.load_store()
    print(f"{len(store)} posting(s) in the store")

    for job in store:
        if "myworkdayjobs.com" not in (job.get("url") or ""):
            continue
        salary, description, posted = scraper.fetch_workday_detail(job["url"])
        if description:
            job["description"] = description
        if salary:
            job["salary"] = salary
        if posted and posted != "Unknown":
            # Freeze against NOW, not the entry's found_at: this label was read
            # this second, so it means what it says. freeze_store_posted_labels
            # below anchors on found_at, which is right for a label read back
            # then and wrong for one read just now.
            job["posted"] = scraper.freeze_posted_label(posted, now)
        print(f"  {job.get('company')}: {job.get('title', '')[:48]} → "
              f"{job.get('salary') or 'no salary published'} | {job.get('posted')}")

    store = scraper.freeze_store_posted_labels(store)
    kept = scraper.drop_removed_postings(scraper.purge_old_store(store))
    print(f"\n{len(kept)} posting(s) still live and recent "
          f"({len(store) - len(kept)} aged out or removed)")

    if args.dry_run:
        print("DRY RUN — nothing written")
        return

    scraper.save_store(kept)
    # The feed carries the postings that just aged out too, unlike a normal run
    # where it mirrors the store. Their DB rows are what the dashboard actually
    # renders, and they currently hold the JS-shell junk — no salary and a date
    # bumped to today. One sync of the corrected rows retires them honestly
    # (the dashboard applies its own window, so nothing stale is shown) instead
    # of stranding them on the board with the bug still in them.
    scraper.save_shared_jobs([
        scraper.normalize_shared_job(job, job.get("description", "")) for job in store
    ])
    scraper.save_seen({job["url"] for job in kept})
    scraper.write_html(kept)
    print(f"store ({len(kept)}), feed ({len(store)}), seen set and jobs.html rewritten")


if __name__ == "__main__":
    main()
