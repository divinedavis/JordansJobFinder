"""HR scraper — HR coordinator roles and the level directly above
(generalist / specialist) across the four PA metros.

Writes to shared_jobs_hr.json. Mirrors scraper_it.py: same 7-day recency
(these roles post rarely in small metros; results.BOARD_WINDOW_DAYS matches),
same merged Workday+Greenhouse employer union, same extra-ATS regional
platforms — which are the ONLY reach into York and Lancaster employers
(WellSpan, Fulton Bank, Armstrong, Dentsply, Hershey, …). No salary filter:
HR postings rarely carry pay data and the track doesn't require it.
Coverage: York PA, Lancaster PA, Philadelphia PA, Harrisburg PA.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from scraper_ats_extra import collect_extra_jobs
from scraper_it import IT_GREENHOUSE_COMPANIES, IT_WORKDAY_COMPANIES
from scraper_sales import first_truthy_date, parse_iso, parse_relative_posted
from corporate_filter import is_corporate_role

# Only keep jobs posted within this window (7 days — see module docstring).
RECENCY_DAYS = 7

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_JOBS_FILE = SCRIPT_DIR / "shared_jobs_hr.json"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; JordansJobFinder/hr)",
}

# Reuse the verified sales+finance union assembled by scraper_it.
HR_WORKDAY_COMPANIES = list(IT_WORKDAY_COMPANIES)
HR_GREENHOUSE_COMPANIES = list(IT_GREENHOUSE_COMPANIES)

CITY_LOCATION_PATTERNS = {
    "york-pa":         ["york, pa", "york county"],
    "lancaster-pa":    ["lancaster, pa", "lancaster county"],
    # Penn Medicine's Workday lists campus names, not "Philadelphia, PA" —
    # HUP / Perelman / Pennsylvania Hospital postings must still land.
    "philadelphia-pa": ["philadelphia", "philly", "malvern", "horsham", "blue bell", "wayne, pa", "valley forge", "king of prussia",
                        "hup", "perelman", "pennsylvania hospital", "penn presbyterian", "university city"],
    "harrisburg-pa":   ["harrisburg", "camp hill", "mechanicsburg", "hershey, pa"],
}

HR_SEARCH_TERMS = [
    "hr coordinator",
    "human resources coordinator",
    "hr generalist",
    "human resources generalist",
    "hr specialist",
]

# Keep these keyword tuples in sync with app/matching.py::title_is_hr.
HR_ROLE_KEYWORDS = (
    "hr coordinator", "human resources coordinator",
    "people operations coordinator", "hr operations coordinator",
    "hr generalist", "human resources generalist",
    "hr specialist", "human resources specialist",
)
HR_NEGATIVE_KEYWORDS = (
    "director", "vice president", " vp", "vp ", "head of", "chief",
    "intern", "internship",
)


def title_is_hr(title: str) -> bool:
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not t:
        return False
    if not is_corporate_role(t):
        return False
    if any(neg in t for neg in HR_NEGATIVE_KEYWORDS):
        return False
    return any(kw in t for kw in HR_ROLE_KEYWORDS)


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
        "vertical": "hr",
        "found_at": datetime.now(timezone.utc).isoformat(),
    }


def _workday_detail_locations(tenant, wd_ver, site, ext_path):
    """Real cities for 'N Locations' postings (same fix as scraper_it)."""
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
    for term in HR_SEARCH_TERMS:
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
                if not title_is_hr(title):
                    continue
                posted_label = job.get("postedOn", "") or ""
                posted_dt = parse_relative_posted(posted_label)
                if not within_recency(posted_dt):
                    continue
                ext_path = job.get("externalPath", "")
                city = infer_city(location)
                if not city and _MULTI_LOCATION_RE.match((location or "").strip()):
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
                    location=location, source="workday-hr",
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
        if not title_is_hr(title):
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
            city=city, location=location, source="greenhouse-hr",
            posted_dt=posted_dt, posted_label=label,
        ))
    return found


def main() -> int:
    all_jobs = []
    for name, tenant, ver, site in HR_WORKDAY_COMPANIES:
        print(f"[Workday] {name}…")
        all_jobs.extend(scrape_workday(name, tenant, ver, site))
        time.sleep(0.4)
    for name, token in HR_GREENHOUSE_COMPANIES:
        print(f"[Greenhouse] {name}…")
        all_jobs.extend(scrape_greenhouse(name, token))
        time.sleep(0.3)

    # Regional PA employers on Oracle/Lever/iCIMS/SuccessFactors — the only
    # way to reach York and Lancaster.
    print("[Extra ATS] Oracle/Lever/Phenom/iCIMS/SuccessFactors…")
    all_jobs.extend(collect_extra_jobs(
        title_filter=title_is_hr,
        infer_city=infer_city,
        within_recency=within_recency,
        make_job=make_job,
        source_suffix="hr",
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
    print(f"\nWrote {len(deduped)} HR jobs -> {SHARED_JOBS_FILE}")
    by_city = {}
    for j in deduped:
        by_city.setdefault(j["city"], 0)
        by_city[j["city"]] += 1
    for c, n in sorted(by_city.items()):
        print(f"  {c}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
