"""Finance scraper — entry-level analyst/associate roles at curated employers.

Writes to shared_jobs_finance.json. Companion to scraper.py (PM/PgM). Both
files get ingested by app/sync.py:upsert_shared_jobs and tagged with their
vertical so the dashboard tabs surface the right roles.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Only keep jobs posted within this window.
RECENCY_DAYS = 2

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_JOBS_FILE = SCRIPT_DIR / "shared_jobs_finance.json"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; JordansJobFinder/finance)",
}

# Workday: (name, tenant, wd_ver, site).
# Every entry below was verified to return HTTP 200 for these search terms on
# 2026-05-27. Tenants that 422'd were dropped (BNY Mellon, Deutsche Bank,
# Barclays, HSBC, UBS, Citadel, D.E. Shaw, Jane Street, Jefferies, etc.) —
# their public APIs don't accept this query shape, so leaving them in only
# pollutes the log with noise. Future expansion should probe with the
# diagnostic in CLAUDE.md before adding to this list.
FINANCE_WORKDAY_COMPANIES = [
    # PA/MD anchored
    ("Vanguard",        "vanguard",     5, "vanguard_external"),
    ("T. Rowe Price",   "troweprice",   5, "TRowePrice"),
    ("Comcast",         "comcast",      5, "Comcast_Careers"),
    # Big NYC finance + insurance + fintech (verified Workday tenants)
    ("Morgan Stanley",  "ms",           5, "External"),
    ("BlackRock",       "blackrock",    1, "BlackRock_Professional"),
    ("Bank of America", "ghr",          1, "Lateral-US"),
    ("Wells Fargo",     "wf",           1, "WellsFargoJobs"),
    ("Fidelity",        "fmr",          1, "FidelityCareers"),
    ("TIAA",            "tiaa",         1, "Search"),
    ("State Street",    "statestreet",  1, "Global"),
    ("Prudential",      "pru",          5, "Careers"),
    ("Mastercard",      "mastercard",   1, "CorporateCareers"),
    ("S&P Global",      "spgi",         5, "SPGI_Careers"),
    ("Nasdaq",          "nasdaq",       1, "US_External_Career_Site"),
    ("Apollo",          "athene",       5, "Apollo_Careers"),
    ("Blackstone",      "blackstone",   1, "Blackstone_Careers"),
    ("AIG",             "aig",          1, "aig"),
    ("The Hartford",    "thehartford",  5, "Careers_External"),
    ("Nationwide",      "nationwide",   1, "Nationwide_Career"),
    ("Travelers",       "travelers",    5, "External"),
]

# Greenhouse: (name, token). Token "coinbase" 404'd — Coinbase moved boards.
FINANCE_GREENHOUSE_COMPANIES = [
    ("Bridgewater",     "bridgewater89"),
    ("Point72",         "point72"),
    ("AQR Capital",     "aqr"),
    ("Robinhood",       "robinhood"),
    ("Affirm",          "affirm"),
    ("SoFi",            "sofi"),
    ("Stripe",          "stripe"),
    ("Chime",           "chime"),
    ("Brex",            "brex"),
    ("Marqeta",         "marqeta"),
    ("Block",           "block"),
    ("Gemini",          "gemini"),
    ("Virtu Financial", "virtu"),
    ("Jump Trading",    "jumptrading"),
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


def parse_relative_posted(text: str) -> "datetime | None":
    """Parse Workday's relative postedOn ('Posted Today', 'Posted Yesterday',
    'Posted 3 Days Ago', 'Posted 30+ Days Ago', etc.) into a UTC datetime.
    Returns None when the string can't be parsed."""
    if not text:
        return None
    t = text.lower().strip()
    now = datetime.now(timezone.utc)
    if "today" in t or "just posted" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", t)
    if m:
        return now - timedelta(days=int(m.group(1)))
    # Some ATSs return ISO datetimes; tolerate.
    try:
        dt = datetime.fromisoformat(t.replace("z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def within_recency(posted_dt: "datetime | None") -> bool:
    """True iff posted_dt is within RECENCY_DAYS of now. None means unknown
    — we drop those rather than guessing, since the user explicitly wants
    only fresh finance jobs."""
    if posted_dt is None:
        return False
    return (datetime.now(timezone.utc) - posted_dt).days <= RECENCY_DAYS


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
        "vertical": "finance",
        "found_at": datetime.now(timezone.utc).isoformat(),
    }


def scrape_workday(name, tenant, wd_ver, site):
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
                posted_label = job.get("postedOn", "") or ""
                posted_dt = parse_relative_posted(posted_label)
                if not within_recency(posted_dt):
                    continue
                ext_path = job.get("externalPath", "")
                url = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/en-US/{site}{ext_path}"
                found.append(make_job(
                    company=name, title=title, url=url, city=city,
                    location=location, source="workday-finance",
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
        if not title_is_finance_entry(title):
            continue
        city = infer_city(location)
        if not city:
            continue
        updated_raw = (job.get("updated_at") or "")[:19]
        posted_dt = None
        if updated_raw:
            try:
                posted_dt = datetime.fromisoformat(updated_raw).replace(tzinfo=timezone.utc)
            except ValueError:
                posted_dt = None
        if not within_recency(posted_dt):
            continue
        found.append(make_job(
            company=name, title=title, url=job.get("absolute_url", ""),
            city=city, location=location, source="greenhouse-finance",
            posted_dt=posted_dt,
            posted_label=updated_raw[:10] if updated_raw else "",
        ))
    return found


def main() -> int:
    all_jobs = []
    for name, tenant, ver, site in FINANCE_WORKDAY_COMPANIES:
        print(f"[Workday] {name}…")
        all_jobs.extend(scrape_workday(name, tenant, ver, site))
        time.sleep(0.4)
    for name, token in FINANCE_GREENHOUSE_COMPANIES:
        print(f"[Greenhouse] {name}…")
        all_jobs.extend(scrape_greenhouse(name, token))
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
