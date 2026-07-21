"""IT project/program manager scraper — mid-to-senior IT PM roles at $1B+
employers.

Writes to shared_jobs_it.json. Mirrors scraper_sales.py: same 2-day recency,
same Workday+Greenhouse pipeline and extra-ATS regional platforms, swapping in
IT-PM search terms, title keywords, and its own location map: Lancaster PA,
Philadelphia PA, Harrisburg PA, plus EVERY Florida metro (Miami, Tampa,
Orlando, Jacksonville, and a Florida catch-all). Jobs only need to SIT in one
of these locations — company HQ doesn't matter. There is no salary filter and
no seniority ceiling: the track serves a 10+ years user who qualifies for
every level.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from scraper_ats_extra import collect_extra_jobs
from greenhouse_urls import greenhouse_job_url
from metros import infer_metro
from scraper_finance import (
    FINANCE_GREENHOUSE_COMPANIES,
    FINANCE_WORKDAY_COMPANIES,
)
from scraper_sales import (
    SALES_GREENHOUSE_COMPANIES,
    SALES_WORKDAY_COMPANIES,
    first_truthy_date,
    parse_iso,
    parse_relative_posted,
)
from corporate_filter import is_corporate_role

# Only keep jobs posted within this window. Wider than the 2-day national
# tracks: senior IT-PM roles in the PA/FL metros post less frequently, and the
# dashboard shows this vertical a 7-day board (results.BOARD_WINDOW_DAYS).
RECENCY_DAYS = 7

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_JOBS_FILE = SCRIPT_DIR / "shared_jobs_it.json"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; JordansJobFinder/it)",
}

# Union of BOTH verified $1B+ / regional employer sets (sales + finance) —
# every endpoint returned HTTP 200 from the droplet IP. The finance list adds
# the banks/insurers with big PA and FL technology hubs (Vanguard in Malvern,
# Fidelity in Jacksonville, Raymond James in Tampa, …). The per-scraper title
# filter keeps the verticals from claiming each other's jobs.
def _merge_unique(*lists, key):
    seen, out = set(), []
    for lst in lists:
        for entry in lst:
            k = key(entry)
            if k in seen:
                continue
            seen.add(k)
            out.append(entry)
    return out


IT_WORKDAY_COMPANIES = _merge_unique(
    SALES_WORKDAY_COMPANIES, FINANCE_WORKDAY_COMPANIES,
    key=lambda e: (e[1], e[2], e[3]),  # (tenant, wd_ver, site)
)
IT_GREENHOUSE_COMPANIES = _merge_unique(
    SALES_GREENHOUSE_COMPANIES, FINANCE_GREENHOUSE_COMPANIES,
    key=lambda e: e[1],  # token
)

# Location patterns per city slug. Order matters: the generic Florida
# catch-all MUST be checked last so the named FL metros claim their postings
# first (same trick as Dallas-last in scraper.py's infer_pm_city).

IT_SEARCH_TERMS = [
    "it project manager",
    "it program manager",
    "technical project manager",
    "technical program manager",
    "infrastructure project manager",
    "erp project manager",
    "software program manager",
    "pmo manager",
]

# A matching title must be a project/program-management role AND carry an
# IT/technology signal (or a standalone "IT" word). Keep these three tuples in
# sync with app/matching.py::title_is_it_pm.
IT_PM_ROLE_KEYWORDS = (
    "project manager", "program manager",
    "project management", "program management",
)
IT_TITLE_SIGNALS = (
    "information technology", "information systems", "information security",
    "technical", "technology", "software", "infrastructure", "cyber",
    "security", "cloud", "erp", "sap", "crm", "salesforce", "digital",
    "data", "application", "systems", "network", "devops", "agile",
    "scrum", "pmo", "implementation", "integration",
)
IT_NEGATIVE_KEYWORDS = (
    "construction", "civil", "clinical", "facilities", "hvac",
    "electrical", "mechanical", "plumbing", "landscap", "roofing",
    "wastewater", "highway", "bridge", "real estate", "property",
)


def title_is_it_pm(title: str) -> bool:
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not t:
        return False
    if not is_corporate_role(t):
        return False
    if any(neg in t for neg in IT_NEGATIVE_KEYWORDS):
        return False
    if not any(kw in t for kw in IT_PM_ROLE_KEYWORDS):
        return False
    if re.search(r"\bit\b", t):
        return True
    return any(sig in t for sig in IT_TITLE_SIGNALS)


def within_recency(posted_dt):
    if posted_dt is None:
        return False
    return (datetime.now(timezone.utc) - posted_dt).days <= RECENCY_DAYS


def infer_city(location):
    """Map an ATS location string to a supported metro code, or "" if none.

    Callers MUST skip postings that return "" — there is no silent fallback to
    the company's HQ, or e.g. Vanguard's Melbourne office floods Philadelphia.

    Every vertical covers the same 29 metros as of 2026-07-21 (the 20 largest
    US metros plus the PA trio and South Carolina); the patterns and their
    collision rules live in metros.py.
    """
    return infer_metro(location)


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
        "is_technical": True,
        "vertical": "it",
        "found_at": datetime.now(timezone.utc).isoformat(),
    }


def _workday_detail_locations(tenant, wd_ver, site, ext_path):
    """All location strings for one posting. Multi-location Workday postings
    list only 'N Locations' on the search result — the real cities live on the
    detail endpoint. Big employers (Fidelity, banks) post most roles this way;
    without this the whole posting is invisible to the location filter."""
    api = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{ext_path}"
    try:
        resp = requests.get(api, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        info = resp.json().get("jobPostingInfo") or {}
        locations = [info.get("location") or ""]
        locations.extend(info.get("additionalLocations") or [])
        return [loc for loc in locations if loc]
    except Exception:
        return []


_MULTI_LOCATION_RE = re.compile(r"^\d+\s+locations$", re.IGNORECASE)


def scrape_workday(name, tenant, wd_ver, site):
    api = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    found = []
    for term in IT_SEARCH_TERMS:
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
                if not title_is_it_pm(title):
                    continue
                posted_label = job.get("postedOn", "") or ""
                posted_dt = parse_relative_posted(posted_label)
                if not within_recency(posted_dt):
                    continue
                ext_path = job.get("externalPath", "")
                city = infer_city(location)
                if not city and _MULTI_LOCATION_RE.match((location or "").strip()):
                    # "N Locations" hides the real cities — pull the detail
                    # page (only for title+recency survivors) and keep the
                    # first location inside the track's metros.
                    for loc in _workday_detail_locations(tenant, wd_ver, site, ext_path):
                        city = infer_city(loc)
                        if city:
                            location = loc
                            break
                if not city:
                    continue
                url = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/en-US/{site}{ext_path}"
                found.append(make_job(
                    company=name, title=title, url=url, city=city,
                    location=location, source="workday-it",
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
        if not title_is_it_pm(title):
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
            company=name, title=title, url=greenhouse_job_url(job, token),
            city=city, location=location, source="greenhouse-it",
            posted_dt=posted_dt, posted_label=label,
        ))
    return found


def main() -> int:
    all_jobs = []
    for name, tenant, ver, site in IT_WORKDAY_COMPANIES:
        print(f"[Workday] {name}…")
        all_jobs.extend(scrape_workday(name, tenant, ver, site))
        time.sleep(0.4)
    for name, token in IT_GREENHOUSE_COMPANIES:
        print(f"[Greenhouse] {name}…")
        all_jobs.extend(scrape_greenhouse(name, token))
        time.sleep(0.3)

    # Regional PA employers on non-Workday/Greenhouse platforms (WellSpan,
    # Fulton, Armstrong, Hershey, …) — the only way to reach Lancaster and
    # the Harrisburg locals; they all clear the $1B revenue bar.
    print("[Extra ATS] Oracle/Lever/Phenom/iCIMS/SuccessFactors…")
    all_jobs.extend(collect_extra_jobs(
        title_filter=title_is_it_pm,
        infer_city=infer_city,
        within_recency=within_recency,
        make_job=make_job,
        source_suffix="it",
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
    print(f"\nWrote {len(deduped)} IT PM jobs -> {SHARED_JOBS_FILE}")
    by_city = {}
    for j in deduped:
        by_city.setdefault(j["city"], 0)
        by_city[j["city"]] += 1
    for c, n in sorted(by_city.items()):
        print(f"  {c}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
