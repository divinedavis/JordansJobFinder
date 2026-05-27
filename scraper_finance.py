"""Finance scraper — entry-level analyst/associate roles at curated employers.

Writes to shared_jobs_finance.json. Companion to scraper.py (PM/PgM). Both
files get ingested by app/sync.py:upsert_shared_jobs and tagged with their
vertical so the dashboard tabs surface the right roles.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_JOBS_FILE = SCRIPT_DIR / "shared_jobs_finance.json"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; JordansJobFinder/finance)",
}

# Workday: (name, tenant, wd_ver, site, city)
FINANCE_WORKDAY_COMPANIES = [
    ("Vanguard",      "vanguard",   5, "vanguard_external", "philadelphia-pa"),
    ("T. Rowe Price", "troweprice", 5, "TRowePrice",        "baltimore-md"),
    ("Comcast",       "comcast",    5, "Comcast_Careers",   "philadelphia-pa"),
]

# Greenhouse: (name, token, default_city)
FINANCE_GREENHOUSE_COMPANIES = [
    ("Bridgewater", "bridgewater89", "nyc"),
    ("Point72",     "point72",       "nyc"),
    ("AQR Capital", "aqr",           "nyc"),
    ("Robinhood",   "robinhood",     "nyc"),
]

# Locations that count for each city code (substring match against the ATS location string)
CITY_LOCATION_PATTERNS = {
    "nyc":             ["new york", "manhattan", " nyc", "ny,", " ny "],
    "atlanta":         ["atlanta", "ga,", " ga "],
    "miami":           ["miami", "fl,", " fl "],
    "dallas":          ["dallas", "plano", "frisco", "irving"],
    "houston":         ["houston"],
    "dc":              ["washington, dc", "washington dc", "arlington", "alexandria", "mclean", "reston"],
    "york-pa":         ["york, pa", "york county"],
    "lancaster-pa":    ["lancaster, pa", "lancaster county"],
    "philadelphia-pa": ["philadelphia", "philly", "malvern", "horsham", "blue bell", "wayne, pa", "valley forge", "king of prussia"],
    "harrisburg-pa":   ["harrisburg", "camp hill", "mechanicsburg", "hershey, pa"],
    "baltimore-md":    ["baltimore", "owings mills", "columbia, md", "owings, md", "towson"],
}

FINANCE_SEARCH_TERMS = [
    "financial analyst",
    "analyst",
    "audit",
    "associate",
    "fp&a",
    "treasury",
]

# Title keywords that mark a job as entry-level finance
FINANCE_TITLE_KEYWORDS = (
    "financial analyst", "finance analyst", "fp&a",
    "investment banking", "investment analyst", "investment associate",
    "audit", "tax associate", "tax staff",
    "credit analyst", "underwriting", "underwriter",
    "actuarial", "treasury", "risk analyst",
    "compliance analyst", "operations analyst",
    "research associate", "research analyst",
)

# Negative title keywords — skip these
NEGATIVE_TITLE_KEYWORDS = (
    "senior", "principal", "lead", "staff", "director",
    "vp", "vice president", "head of", "manager", "managing",
    "engineer", "engineering",
)


def title_is_finance_entry(title: str) -> bool:
    t = (title or "").lower().strip()
    if not t:
        return False
    if any(neg in t for neg in NEGATIVE_TITLE_KEYWORDS):
        return False
    if any(kw in t for kw in FINANCE_TITLE_KEYWORDS):
        return True
    if "analyst" in t or "associate" in t:
        return True
    return False


def infer_city(location: str) -> str:
    """Map an ATS location string to a supported city code.

    Returns "" if the location does not match any of the 11 supported metros —
    callers MUST skip these jobs (no silent fallback to the company's HQ,
    otherwise e.g. Vanguard's Melbourne office floods Philadelphia)."""
    loc = (location or "").lower()
    for code, patterns in CITY_LOCATION_PATTERNS.items():
        if any(p in loc for p in patterns):
            return code
    return ""


def make_job(*, company, title, url, city, location, source, posted_at):
    return {
        "source": source,
        "company": company,
        "title": title,
        "normalized_title": re.sub(r"\s+", " ", title.strip().lower()),
        "url": url,
        "city": city,
        "location": location,
        "description": "",
        "salary_label": "",
        "salary_min": None,
        "salary_max": None,
        "posted_label": posted_at[:10] if posted_at else "",
        "posted_at": posted_at,
        "experience_min": None,
        "experience_max": None,
        "is_technical": False,
        "vertical": "finance",
        "found_at": datetime.now(timezone.utc).isoformat(),
    }


def scrape_workday(name, tenant, wd_ver, site, default_city):
    api = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    found = []
    for term in FINANCE_SEARCH_TERMS:
        offset = 0
        while True:
            try:
                resp = requests.post(
                    api,
                    json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term},
                    headers=HEADERS,
                    timeout=15,
                )
                if resp.status_code != 200:
                    if offset == 0:
                        print(f"  [{name}/{term}] HTTP {resp.status_code}")
                    break
                data = resp.json()
            except Exception as exc:
                print(f"  [{name}/{term}] error: {exc}")
                break
            postings = data.get("jobPostings", [])
            total = data.get("total", 0)
            for job in postings:
                title = job.get("title", "")
                location = job.get("locationsText", "")
                if not title_is_finance_entry(title):
                    continue
                city = infer_city(location)
                if not city:
                    continue
                ext_path = job.get("externalPath", "")
                url = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/en-US/{site}{ext_path}"
                found.append(make_job(
                    company=name, title=title, url=url, city=city,
                    location=location, source="workday-finance",
                    posted_at=job.get("postedOn", "") or "",
                ))
            offset += 20
            if offset >= total or not postings:
                break
            time.sleep(0.3)
    return found


def scrape_greenhouse(name, token, default_city):
    api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    try:
        resp = requests.get(api, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)
        if resp.status_code != 200:
            print(f"  [{name}] HTTP {resp.status_code}")
            return []
        jobs = resp.json().get("jobs", [])
    except Exception as exc:
        print(f"  [{name}] error: {exc}")
        return []
    found = []
    for job in jobs:
        title = job.get("title", "")
        location = job.get("location", {}).get("name", "")
        if not title_is_finance_entry(title):
            continue
        city = infer_city(location)
        if not city:
            continue
        found.append(make_job(
            company=name, title=title, url=job.get("absolute_url", ""),
            city=city, location=location, source="greenhouse-finance",
            posted_at=(job.get("updated_at") or "")[:19],
        ))
    return found


def main() -> int:
    all_jobs = []
    for name, tenant, ver, site, city in FINANCE_WORKDAY_COMPANIES:
        print(f"[Workday] {name}…")
        all_jobs.extend(scrape_workday(name, tenant, ver, site, city))
        time.sleep(0.4)
    for name, token, city in FINANCE_GREENHOUSE_COMPANIES:
        print(f"[Greenhouse] {name}…")
        all_jobs.extend(scrape_greenhouse(name, token, city))
        time.sleep(0.3)

    # Dedupe by URL
    seen = set()
    deduped = []
    for job in all_jobs:
        if not job.get("url") or job["url"] in seen:
            continue
        seen.add(job["url"])
        deduped.append(job)

    SHARED_JOBS_FILE.write_text(json.dumps(deduped, indent=2))
    print(f"\nWrote {len(deduped)} finance jobs -> {SHARED_JOBS_FILE}")
    by_city = {}
    for j in deduped:
        by_city.setdefault(j["city"], 0)
        by_city[j["city"]] += 1
    for c, n in sorted(by_city.items()):
        print(f"  {c}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
