"""Supply Chain Management scraper — supply-chain / logistics / procurement
roles (plus manufacturing-operations ICs) at $1B+ employers across the
top-10 US metros, Atlanta/Miami/DC, and South Carolina's major metros
(nationwide expansion 2026-07-19; originally SC-only).

Writes to shared_jobs_scm.json. Mirrors scraper_hr.py: same 7-day recency
(SC roles post sparsely; results.BOARD_WINDOW_DAYS matches), same merged
$1B+ Workday+Greenhouse employer union plus the verified Charleston-area
employers, plus the regional extra-ATS platforms. No salary requirement —
the $1B+-employer and SC-location constraints do the filtering.

Metros (slug -> label): charleston-sc (Lowcountry), columbia-sc (Midlands),
greenville-sc (Upstate incl. Spartanburg), rock-hill-sc (York County).
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
from scraper_sc_employers import SC_GREENHOUSE_1B, SC_WORKDAY_1B
from corporate_filter import is_corporate_role

RECENCY_DAYS = 7

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_JOBS_FILE = SCRIPT_DIR / "shared_jobs_scm.json"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; JordansJobFinder/scm)",
}

# $1B+ employer union (verified sales+finance set from scraper_it) plus the
# verified Charleston-area employers, plus the full verified SC $1B+ registry
# (scraper_sc_employers) — the major SC employers across all four metros.
# Top-10-city $1B+ wave (2026-07-19) — manufacturing/health/consumer
# employers with heavy supply-chain orgs. Endpoints verified from droplet.
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

_CHARLESTON = [
    ("Boeing", "boeing", 1, "EXTERNAL_CAREERS"),
    ("Ingevity", "ingevity", 1, "Ingevity"),
    ("SouthState Bank", "southstatebank", 5, "External"),
]


def _merge(*lists, key):
    seen, out = set(), []
    for lst in lists:
        for e in lst:
            k = key(e)
            if k in seen:
                continue
            seen.add(k)
            out.append(e)
    return out


SCM_WORKDAY_COMPANIES = _merge(
    IT_WORKDAY_COMPANIES, _CHARLESTON, SC_WORKDAY_1B, _TOP10_WAVE,
    key=lambda e: (e[1], e[2], e[3]),
)
SCM_GREENHOUSE_COMPANIES = _merge(
    IT_GREENHOUSE_COMPANIES, SC_GREENHOUSE_1B, key=lambda e: e[1],
)

# Metro-level SC inference. Order-independent (no overlaps between metros).
CITY_LOCATION_PATTERNS = {
    # SC metros first (original track scope; no overlaps with each other).
    "charleston-sc":  ["charleston", "north charleston", "mount pleasant",
                       "mt pleasant", "summerville", "ladson", "goose creek",
                       "moncks corner", "hanahan", "daniel island", "ridgeville"],
    "columbia-sc":    ["columbia, sc", "columbia sc", "lexington, sc",
                       "west columbia", "cayce", "irmo", "blythewood",
                       "richland county"],
    "greenville-sc":  ["greenville, sc", "greenville sc", "spartanburg",
                       "greer", "simpsonville", "mauldin", "anderson, sc",
                       "easley", "duncan, sc", "upstate"],
    "rock-hill-sc":   ["rock hill", "fort mill", "york, sc", "york county, sc",
                       "tega cay", "clover, sc"],
    # Nationwide metros (2026-07-19 expansion). Same ordering rules as
    # scraper.py PM_METROS: specific metros before Dallas (whose list carries
    # broad ", tx"/"texas" catch-alls); Phoenix before LA so "glendale, az"
    # beats LA's bare "glendale".
    "nyc":            ["new york", "nyc", "manhattan", "brooklyn", "jersey city"],
    "miami":          ["miami", "miami beach", "fort lauderdale", "boca raton",
                       "doral", "coral gables", "south florida"],
    "atlanta":        ["atlanta", "alpharetta", "sandy springs", "dunwoody"],
    "chicago":        ["chicago", "evanston", "naperville", "schaumburg",
                       "rosemont, il", "oak brook", "deerfield, il",
                       "vernon hills", "lincolnshire", "northbrook",
                       "downers grove", "des plaines", "skokie", "itasca",
                       "hoffman estates", "lake forest, il"],
    "phoenix":        ["phoenix", "scottsdale", "tempe", "chandler",
                       "mesa, az", "gilbert, az", "glendale, az",
                       "peoria, az", "goodyear, az"],
    "san-antonio":    ["san antonio", "new braunfels", "schertz", "windcrest"],
    "san-diego":      ["san diego", "la jolla", "carlsbad", "sorrento valley",
                       "chula vista", "oceanside", "escondido", "encinitas",
                       "poway", "rancho bernardo"],
    "jacksonville-fl": ["jacksonville", "ponte vedra", "orange park, fl"],
    "philadelphia-pa": ["philadelphia", "philly", "conshohocken",
                        "king of prussia", "wayne, pa", "radnor", "malvern",
                        "horsham", "camden, nj", "wilmington, de",
                        "chesterbrook", "plymouth meeting", "blue bell",
                        "west chester, pa", "newtown square"],
    "la":             ["los angeles", "santa monica", "culver city",
                       "long beach", "burbank", "el segundo", "torrance",
                       "irvine", "newport beach", "woodland hills",
                       "manhattan beach", "beverly hills"],
    "dc":             ["washington", "d.c.", "arlington, va", "mclean",
                       "tysons", "reston", "bethesda", "rockville",
                       "alexandria", "fairfax"],
    "houston":        ["houston", "the woodlands", "sugar land", "katy",
                       "pearland", "baytown"],
    "dallas":         ["dallas", "fort worth", "dfw", "plano", "irving",
                       "frisco", "richardson", "addison", "tx,", ", tx",
                       "texas"],
}

SCM_SEARCH_TERMS = [
    "supply chain", "logistics", "procurement", "sourcing", "buyer",
    "materials", "demand planning", "warehouse", "distribution",
    # 2026-07-19: manufacturing-operations ICs
    "production planner", "quality engineer", "manufacturing engineer",
    "process engineer", "continuous improvement",
]

# Keep in sync with app/matching.py::SCM_KEYWORDS.
SCM_KEYWORDS = (
    "supply chain", "logistics", "procurement", "sourcing", "purchasing",
    "materials manager", "materials management", "demand planning",
    "supply planning", "inventory", "distribution", "warehouse",
    "fulfillment", "s&op", "buyer", "commodity manager", "category manager",
    "supply chain planner", "operations planner", "logistics coordinator",
    # 2026-07-19: manufacturing-operations ICs. Keep in sync with
    # app/matching.py::SCM_KEYWORDS.
    "production planner", "master scheduler", "production scheduler",
    "quality engineer", "quality analyst", "supplier quality",
    "manufacturing engineer", "process engineer", "industrial engineer",
    "continuous improvement", "lean six sigma", "ehs specialist",
)
SCM_NEGATIVE_KEYWORDS = ("intern", "internship")


def title_is_scm(title: str) -> bool:
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not t:
        return False
    if not is_corporate_role(t):
        return False
    if any(neg in t for neg in SCM_NEGATIVE_KEYWORDS):
        return False
    return any(kw in t for kw in SCM_KEYWORDS)


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


def make_job(*, company, title, url, city, location, source, posted_dt,
             posted_label, vertical="scm"):
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
        "vertical": vertical,
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


def scrape_workday(name, tenant, wd_ver, site, title_filter=title_is_scm,
                   vertical="scm", source_suffix="scm", search_terms=None):
    api = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    found = []
    for term in (search_terms or SCM_SEARCH_TERMS):
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
                if not title_filter(title):
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
                    location=location, source=f"workday-{source_suffix}",
                    posted_dt=posted_dt, posted_label=posted_label,
                    vertical=vertical,
                ))
            offset += 20
            if offset >= total or not postings:
                break
            time.sleep(0.3)
    return found


def scrape_greenhouse(name, token, title_filter=title_is_scm,
                      vertical="scm", source_suffix="scm"):
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
        if not title_filter(title):
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
            city=city, location=location, source=f"greenhouse-{source_suffix}",
            posted_dt=posted_dt, posted_label=label, vertical=vertical,
        ))
    return found


def run(*, title_filter=title_is_scm, vertical="scm", source_suffix="scm",
        search_terms=None, out_file=SHARED_JOBS_FILE, label="SCM") -> int:
    """Scrape the SC $1B+ employer union for one role vertical.

    The SC employers, metros, and recency are shared; only the title filter and
    the vertical tag change per role track (SCM, Project Management, …).
    """
    all_jobs = []
    for name, tenant, ver, site in SCM_WORKDAY_COMPANIES:
        print(f"[Workday] {name}…")
        all_jobs.extend(scrape_workday(
            name, tenant, ver, site, title_filter=title_filter,
            vertical=vertical, source_suffix=source_suffix,
            search_terms=search_terms,
        ))
        time.sleep(0.4)
    for name, token in SCM_GREENHOUSE_COMPANIES:
        print(f"[Greenhouse] {name}…")
        all_jobs.extend(scrape_greenhouse(
            name, token, title_filter=title_filter,
            vertical=vertical, source_suffix=source_suffix,
        ))
        time.sleep(0.3)

    print("[Extra ATS] Oracle/Lever/Phenom/iCIMS/SuccessFactors…")
    all_jobs.extend(collect_extra_jobs(
        title_filter=title_filter,
        infer_city=infer_city,
        within_recency=within_recency,
        make_job=lambda **kw: make_job(vertical=vertical, **kw),
        source_suffix=source_suffix,
    ))

    seen = set()
    deduped = []
    for job in all_jobs:
        if not job.get("url") or job["url"] in seen:
            continue
        seen.add(job["url"])
        deduped.append(job)

    out_file.write_text(json.dumps(deduped, indent=2))
    print(f"\nWrote {len(deduped)} {label} jobs -> {out_file}")
    by_city = {}
    for j in deduped:
        by_city.setdefault(j["city"], 0)
        by_city[j["city"]] += 1
    for c, n in sorted(by_city.items()):
        print(f"  {c}: {n}")
    return 0


def run_multi(tracks) -> int:
    """One pass over the employer union serving several role tracks at once.

    ``tracks`` is a list of dicts: {title_filter, vertical, source_suffix,
    search_terms, out_file, label}. Workday boards are queried once per
    DEDUPED union search term and every posting is tested against every
    track's title filter (a posting surfaced by an SCM term can still land
    on the analyst board — the filter, not the term, decides membership).
    Greenhouse boards are fetched once total instead of once per track.
    This replaced three sequential full sweeps (scm/project/analyst) that
    tripled the nightly chain's runtime (2026-07-20).
    """
    union_terms, seen_terms = [], set()
    for track in tracks:
        for term in track["search_terms"]:
            if term not in seen_terms:
                seen_terms.add(term)
                union_terms.append(term)

    per_track: dict[str, list] = {t["vertical"]: [] for t in tracks}

    def _multi_filter(title):
        return any(t["title_filter"](title) for t in tracks)

    def _route(jobs):
        for job in jobs:
            for track in tracks:
                if track["title_filter"](job["title"]):
                    routed = dict(job)
                    routed["vertical"] = track["vertical"]
                    routed["source"] = re.sub(
                        r"-[a-z]+$", f"-{track['source_suffix']}", routed["source"]
                    )
                    per_track[track["vertical"]].append(routed)

    for name, tenant, ver, site in SCM_WORKDAY_COMPANIES:
        print(f"[Workday] {name}…")
        _route(scrape_workday(
            name, tenant, ver, site, title_filter=_multi_filter,
            vertical="multi", source_suffix="multi", search_terms=union_terms,
        ))
        time.sleep(0.4)
    for name, token in SCM_GREENHOUSE_COMPANIES:
        print(f"[Greenhouse] {name}…")
        _route(scrape_greenhouse(
            name, token, title_filter=_multi_filter,
            vertical="multi", source_suffix="multi",
        ))
        time.sleep(0.3)

    # Extra-ATS collectors are cheap relative to the board sweeps; run them
    # per track so vertical tagging stays unambiguous.
    for track in tracks:
        print(f"[Extra ATS] {track['label']}…")
        per_track[track["vertical"]].extend(collect_extra_jobs(
            title_filter=track["title_filter"],
            infer_city=infer_city,
            within_recency=within_recency,
            make_job=lambda **kw: make_job(vertical=track["vertical"], **kw),
            source_suffix=track["source_suffix"],
        ))

    for track in tracks:
        jobs = per_track[track["vertical"]]
        seen, deduped = set(), []
        for job in jobs:
            if not job.get("url") or job["url"] in seen:
                continue
            seen.add(job["url"])
            deduped.append(job)
        track["out_file"].write_text(json.dumps(deduped, indent=2))
        print(f"\nWrote {len(deduped)} {track['label']} jobs -> {track['out_file']}")
        by_city = {}
        for j in deduped:
            by_city.setdefault(j["city"], 0)
            by_city[j["city"]] += 1
        for c, n in sorted(by_city.items()):
            print(f"  {c}: {n}")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
