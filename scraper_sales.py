"""Sales scraper — entry-level SDR/BDR/AE/SE roles at curated employers.

Writes to shared_jobs_sales.json. Mirrors scraper_finance.py: same 2-day
recency, same 11-metro location map, same Workday+Greenhouse pipeline,
swapping in sales-relevant search terms, employers, and title keywords.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from scraper_ats_extra import collect_extra_jobs

# Only keep jobs posted within this window.
RECENCY_DAYS = 2

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_JOBS_FILE = SCRIPT_DIR / "shared_jobs_sales.json"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; JordansJobFinder/sales)",
}

# Workday: (name, tenant, wd_ver, site). Verified to return HTTP 200 for these
# query shapes on 2026-05-28. Tenants that 422'd were dropped (Cisco, SAP,
# Oracle, VMware, Splunk) — they don't accept the (appliedFacets, searchText)
# request body. Future expansion should probe with the diagnostic in
# CLAUDE.md before adding to this list.
SALES_WORKDAY_COMPANIES = [
    ("Salesforce",     "salesforce", 12, "External_Career_Site"),
    ("Workday",        "workday",    5,  "Workday"),
    ("Adobe",          "adobe",      5,  "external_experienced"),
    ("Dell",           "dell",       1,  "External"),
    ("Comcast",        "comcast",    5,  "Comcast_Careers"),
    # Regional employers anchored in the PA/MD metros (Harrisburg, Philadelphia,
    # Baltimore — plus York/Lancaster spillover via the location filter). Same
    # verified set as scraper_finance.py FINANCE_WORKDAY_COMPANIES; all returned
    # HTTP 200 against the live jobs API on 2026-05-31. The per-scraper title
    # filter keeps these from claiming finance jobs. Lancaster/York have no
    # dedicated local employer on Workday/Greenhouse (the local names are all on
    # iCIMS/SuccessFactors/Oracle/ADP) — Highmark and M&T are the proxies.
    ("Highmark",               "highmarkhealth", 1,   "highmark"),                          # Harrisburg/Central PA
    ("Rite Aid",               "riteaid",        1,   "External"),                          # Camp Hill (Harrisburg)
    ("FMC",                    "fmc",            12,  "FMC"),                               # Philadelphia
    ("Crown Holdings",         "crownholdings",  501, "CrownHoldings"),                     # Philadelphia (Yardley)
    ("Penn Medicine",          "upenn",          1,   "careers-at-penn"),                   # Philadelphia
    ("M&T Bank",               "mtb",            5,   "MTB"),                               # Baltimore + PA branches
    ("M&T Bank Campus",        "mtb",            5,   "Campus"),                            # early-career programs
    ("Stanley Black & Decker", "sbdinc",         1,   "Stanley_Black_Decker_Career_Site"),  # Baltimore (Towson)
    ("Medifast",               "medifastinc",    108, "Medifast"),                          # Baltimore
    ("Erickson Senior Living", "erickson",       108, "External"),                          # Baltimore (Catonsville)
]

# Greenhouse: (name, token). Verified 200 on 2026-05-28. 404 tokens dropped
# (Snowflake, Gong, Outreach, Notion, Plaid — boards moved or not on
# Greenhouse). Several tokens overlap scraper_finance.py (Stripe, Robinhood,
# Affirm, etc.) — that's fine, the per-scraper title filter keeps the two
# verticals from claiming the same job.
SALES_GREENHOUSE_COMPANIES = [
    ("MongoDB",          "mongodb"),
    ("Datadog",          "datadog"),
    ("Figma",            "figma"),
    ("HubSpot",          "hubspot"),
    ("Stripe",           "stripe"),
    ("Robinhood",        "robinhood"),
    ("Affirm",           "affirm"),
    ("SoFi",             "sofi"),
    ("Chime",            "chime"),
    ("Brex",             "brex"),
    ("Marqeta",          "marqeta"),
    ("Block",            "block"),
    ("Cloudflare",       "cloudflare"),
    ("Samsara",          "samsara"),
    ("ZoomInfo",         "zoominfo"),
]

# Locations that count for each city code (substring match against the ATS
# location string). Same map as scraper_finance.py — keep them in sync.
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

SALES_SEARCH_TERMS = [
    "sales development",
    "business development",
    "account executive",
    "sales representative",
    "inside sales",
    "sales engineer",
    "solutions engineer",
]

# Title keywords that mark a job as entry-level sales
SALES_TITLE_KEYWORDS = (
    "sales development representative", "sdr",
    "business development representative", "bdr",
    "account executive", "ae i", "ae ii",
    "associate account executive", "junior account executive",
    "commercial account executive",
    "sales engineer", "solutions engineer", "solutions consultant",
    "pre-sales", "presales",
    "inside sales", "sales representative", "sales rep",
    "sales associate", "sales specialist",
    "client advisor", "retail sales",
    "outbound sales", "outbound development",
)

# Negative title keywords — skip these. Note "engineer" is intentionally NOT
# here ("Sales Engineer" / "Solutions Engineer" are valid entry roles).
NEGATIVE_TITLE_KEYWORDS = (
    "senior", "principal", "lead", "staff", "director",
    "vp", "vice president", "head of", "manager", "managing",
)


def title_is_sales_entry(title: str) -> bool:
    t = (title or "").lower().strip()
    if not t:
        return False
    if any(neg in t for neg in NEGATIVE_TITLE_KEYWORDS):
        return False
    return any(kw in t for kw in SALES_TITLE_KEYWORDS)


def parse_relative_posted(text):
    """Parse Workday's relative postedOn into a UTC datetime, or None."""
    if not text:
        return None
    t = text.lower().strip()
    now = datetime.now(timezone.utc)
    if "today" in t or "just posted" in t or "moments ago" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*(minute|hour|day|week|month|year)s?", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {
            "minute": timedelta(minutes=n),
            "hour": timedelta(hours=n),
            "day": timedelta(days=n),
            "week": timedelta(weeks=n),
            "month": timedelta(days=n * 30),
            "year": timedelta(days=n * 365),
        }[unit]
        return now - delta
    return parse_iso(t)


def parse_iso(text):
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00").replace("z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def first_truthy_date(*candidates):
    for c in candidates:
        if c is not None:
            return c
    return None


def within_recency(posted_dt):
    if posted_dt is None:
        return False
    return (datetime.now(timezone.utc) - posted_dt).days <= RECENCY_DAYS


def infer_city(location):
    loc = (location or "").lower()
    for code, patterns in CITY_LOCATION_PATTERNS.items():
        if any(p in loc for p in patterns):
            return code
    return ""


def make_job(*, company, title, url, city, location, source, posted_dt, posted_label):
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
        "posted_label": posted_label or "",
        "posted_at": posted_dt.isoformat() if posted_dt else None,
        "experience_min": None,
        "experience_max": None,
        "is_technical": False,
        "vertical": "sales",
        "found_at": datetime.now(timezone.utc).isoformat(),
    }


def scrape_workday(name, tenant, wd_ver, site):
    api = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    found = []
    for term in SALES_SEARCH_TERMS:
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
                if not title_is_sales_entry(title):
                    continue
                city = infer_city(location)
                if not city:
                    continue
                posted_label = job.get("postedOn", "") or ""
                posted_dt = parse_relative_posted(posted_label)
                if not within_recency(posted_dt):
                    continue
                ext_path = job.get("externalPath", "")
                url = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/en-US/{site}{ext_path}"
                found.append(make_job(
                    company=name, title=title, url=url, city=city,
                    location=location, source="workday-sales",
                    posted_dt=posted_dt, posted_label=posted_label,
                ))
            offset += 20
            if offset >= total or not postings:
                break
            time.sleep(0.3)
    return found


def scrape_greenhouse(name, token):
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
        if not title_is_sales_entry(title):
            continue
        city = infer_city(location)
        if not city:
            continue
        posted_dt = first_truthy_date(
            parse_iso(job.get("first_published") or ""),
            parse_iso(job.get("published_at") or ""),
            parse_iso(job.get("created_at") or ""),
            parse_iso(job.get("updated_at") or ""),
        )
        if not within_recency(posted_dt):
            continue
        label = posted_dt.date().isoformat() if posted_dt else ""
        found.append(make_job(
            company=name, title=title, url=job.get("absolute_url", ""),
            city=city, location=location, source="greenhouse-sales",
            posted_dt=posted_dt, posted_label=label,
        ))
    return found


def main() -> int:
    all_jobs = []
    for name, tenant, ver, site in SALES_WORKDAY_COMPANIES:
        print(f"[Workday] {name}…")
        all_jobs.extend(scrape_workday(name, tenant, ver, site))
        time.sleep(0.4)
    for name, token in SALES_GREENHOUSE_COMPANIES:
        print(f"[Greenhouse] {name}…")
        all_jobs.extend(scrape_greenhouse(name, token))
        time.sleep(0.3)

    # Regional employers on non-Workday/Greenhouse platforms (Oracle, Lever,
    # Phenom, iCIMS, SuccessFactors) — the only way to reach the PA/MD local
    # employers (Armstrong, WellSpan, Fulton, Dentsply, Hershey, …).
    print("[Extra ATS] Oracle/Lever/Phenom/iCIMS/SuccessFactors…")
    all_jobs.extend(collect_extra_jobs(
        title_filter=title_is_sales_entry,
        infer_city=infer_city,
        within_recency=within_recency,
        make_job=make_job,
        source_suffix="sales",
    ))

    # Dedupe by URL
    seen = set()
    deduped = []
    for job in all_jobs:
        if not job.get("url") or job["url"] in seen:
            continue
        seen.add(job["url"])
        deduped.append(job)

    SHARED_JOBS_FILE.write_text(json.dumps(deduped, indent=2))
    print(f"\nWrote {len(deduped)} sales jobs -> {SHARED_JOBS_FILE}")
    by_city = {}
    for j in deduped:
        by_city.setdefault(j["city"], 0)
        by_city[j["city"]] += 1
    for c, n in sorted(by_city.items()):
        print(f"  {c}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
