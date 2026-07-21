"""HR scraper — HR coordinator roles and the level directly above
(generalist / specialist) across the four PA metros plus the top-10 US
metros (nationwide expansion 2026-07-19).

Writes to shared_jobs_hr.json. Mirrors scraper_it.py: same 7-day recency
(these roles post rarely in small metros; results.BOARD_WINDOW_DAYS matches),
same merged Workday+Greenhouse employer union, same extra-ATS regional
platforms — which are the ONLY reach into York and Lancaster employers
(WellSpan, Fulton Bank, Armstrong, Dentsply, Hershey, …). No salary filter:
HR postings rarely carry pay data and the track doesn't require it.
Coverage: York PA, Lancaster PA, Philadelphia PA, Harrisburg PA, plus
NYC, Chicago, Phoenix, San Antonio, San Diego, Jacksonville, LA, DC,
Houston, Dallas, Atlanta, Miami (2026-07-19).
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from scraper_ats_extra import collect_extra_jobs
from greenhouse_urls import greenhouse_job_url
from metros import infer_metro
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

# Top-10-city $1B+ wave (2026-07-19) — endpoints verified from the droplet.
_TOP10_WAVE = [
    ("Baxter", "baxter", 1, "baxter"),
    ("CDW", "cdw", 5, "Careers"),
    ("Cboe Global Markets", "cboe", 1, "External_Career_CBOE"),
    ("Conagra Brands", "conagrabrands", 1, "Careers_US"),
    ("GE HealthCare", "gehc", 5, "GEHC_ExternalSite"),
    ("Mondelez", "mdlz", 3, "External"),
    ("Morningstar", "morningstar", 5, "Americas"),
    ("Northern Trust", "ntrs", 1, "northerntrust"),
    ("TransUnion", "transunion", 5, "TransUnion"),
    ("US Foods", "usfoods", 1, "usfoodscareersExternal"),
    ("Wintrust Financial", "wintrust", 1, "Search"),
    ("Zebra Technologies", "zebra", 501, "Zebra_careers"),
    ("PGA Tour", "pgatour", 5, "PGATOURExternal"),
    ("RYAM", "myrayonieram", 5, "careers"),
    ("Ares Management", "aresmgmt", 1, "External"),
    ("Capital Group", "capgroup", 1, "capitalgroupcareers"),
    ("DIRECTV", "directv", 1, "Careers"),
    ("Ingram Micro", "ingrammicro", 5, "IngramMicro"),
    ("Oaktree Capital", "oaktree", 1, "Oaktree"),
    ("Pacific Life", "pacificlife", 1, "PacificLifeCareers"),
    ("Skechers", "skechers", 5, "One-career-site"),
    ("Sony Pictures", "spe", 1, "SonyPicturesEntertainment"),
    ("Universal Music Group", "umusic", 5, "UMGUS"),
    ("Axalta", "axalta", 1, "Axalta"),
    ("Campbell's", "campbellsoup", 5, "ExternalCareers_GlobalSite"),
    ("Carpenter Technology", "cartech", 5, "CTCExternal"),
    ("Cencora", "myhrabc", 5, "Global"),
    ("Chemours", "chemours", 103, "Chemours"),
    ("Crown Holdings", "crownholdings", 501, "CrownHoldings"),
    ("DuPont", "dupont", 5, "Jobs"),
    ("FMC Corporation", "fmc", 12, "FMC"),
    ("Five Below", "fivebelow", 1, "fivebelowcareers"),
    ("Jefferson Health", "jeffersonhealth", 5, "ThomasJeffersonExternal"),
    ("Penn Mutual", "pennmutual", 1, "_penn-careers"),
    ("UPenn", "upenn", 1, "careers-at-penn"),
    ("Banner Health", "bannerhealth", 108, "Careers"),
    ("Microchip Technology", "microchiphr", 5, "External"),
    ("Republic Services", "republic", 5, "Republic"),
    ("Taylor Morrison", "taylormorrison", 1, "TaylorMorrisonCareers"),
    ("U-Haul", "uhaul", 1, "UhaulJobs"),
    ("Western Alliance Bank", "westernalliancebank", 5, "WAB"),
    ("Citigroup", "citi", 5, "2"),
    ("Clear Channel Outdoor", "clearchanneloutdoor", 5, "CCO"),
    ("Frost Bank", "frostbank", 5, "External"),
    ("Rackspace", "rackspace", 1, "External"),
    ("USAA", "usaa", 1, "USAAJOBSWD"),
    ("Whataburger", "whataburger", 5, "WAB_CAREERS"),
    ("iHeartMedia", "iheartmedia", 5, "External_iHM"),
    ("Cubic", "cubic", 1, "cubic_global_careers"),
    ("Dexcom", "dexcom", 1, "Dexcom"),
    ("Illumina", "illumina", 1, "illumina-careers"),
    ("Neurocrine Biosciences", "neurocrine", 5, "Neurocrinecareers"),
    ("Realty Income", "realtyincome", 108, "realty_income_careers"),
    ("ResMed", "resmed", 3, "ResMed_External_Careers"),
    ("Sharp HealthCare", "sharp", 1, "External"),
    ("Sony Electronics", "sonyglobal", 1, "SonyGlobalCareers"),
    ("Topgolf Callaway", "tcbrands", 1, "callaway-careers"),
]

# Reuse the verified sales+finance union assembled by scraper_it.
HR_WORKDAY_COMPANIES = list(IT_WORKDAY_COMPANIES) + [
    e for e in _TOP10_WAVE
    if (e[1], e[2], e[3]) not in {(x[1], x[2], x[3]) for x in IT_WORKDAY_COMPANIES}
]
HR_GREENHOUSE_COMPANIES = list(IT_GREENHOUSE_COMPANIES)


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
            company=name, title=title, url=greenhouse_job_url(job, token),
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
