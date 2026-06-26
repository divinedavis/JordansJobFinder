"""Finance scraper — entry-level analyst/associate roles at curated employers.

Writes to shared_jobs_finance.json. Companion to scraper.py (PM/PgM). Both
files get ingested by app/sync.py:upsert_shared_jobs and tagged with their
vertical so the dashboard tabs surface the right roles.
"""
import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from scraper_ats_extra import collect_extra_jobs
from corporate_filter import is_corporate_role

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
    # Regional employers anchored in the PA/MD metros (Harrisburg, Philadelphia,
    # Baltimore — plus York/Lancaster spillover via the location filter). Every
    # tuple below was verified to return HTTP 200 against the live jobs API on
    # 2026-05-31. Lancaster/York have no dedicated local employer on Workday or
    # Greenhouse (Armstrong/Fulton/Dentsply/WellSpan/Glatfelter are all on
    # iCIMS/SuccessFactors/Oracle/ADP, which this scraper can't read) — Highmark
    # (Central PA) and M&T (PA/MD branches) are the closest reachable proxies.
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

    # ── $1B+ employers (verified HTTP 200 from droplet 2026-06-24) ──────────
    ("Academy Sports", "academy", 1, "Careers"),
    ("Amgen", "amgen", 1, "Careers"),
    ("Analog Devices", "analogdevices", 1, "External"),
    ("Applied Materials", "amat", 1, "External"),
    ("Aptiv", "aptiv", 5, "Aptiv_Careers"),
    ("Avnet", "avnet", 1, "External"),
    ("BorgWarner", "borgwarner", 5, "Borgwarner_Careers"),
    ("Burlington", "burlington", 5, "BurlingtonCareers"),
    ("CNA Financial", "cna", 1, "Cna_Careers"),
    ("Centene", "centene", 5, "Centene_External"),
    ("Chewy", "chewy", 5, "External"),
    ("Chipotle", "chipotle", 5, "ChipotleCareers"),
    ("Choice Hotels", "choicehotels", 5, "External"),
    ("Devon Energy", "devonenergy", 5, "Careers"),
    ("Diageo", "diageo", 3, "Diageo_Careers"),
    ("Ecolab", "ecolab", 1, "Ecolab_External"),
    ("Edwards Lifesciences", "edwards", 5, "EdwardsCareers"),
    ("Everest", "everestre", 5, "External"),
    ("Expedia", "expediagroup", 5, "careers"),
    ("Flex", "flextronics", 1, "Careers"),
    ("Gilead", "gilead", 1, "GileadCareers"),
    ("Goodyear", "goodyear", 1, "GoodyearCareers"),
    ("Illinois Tool Works", "itw", 5, "External"),
    ("Jabil", "jabil", 5, "Jabil_Careers"),
    ("LPL Financial", "lplfinancial", 1, "External"),
    ("Labcorp", "labcorp", 1, "External"),
    ("Las Vegas Sands", "sands", 1, "Sands_Careers"),
    ("Marathon Petroleum", "mpc", 1, "MpcCareers"),
    ("Mars", "mars", 3, "External"),
    ("Marvell", "marvell", 1, "MarvellCareers"),
    ("Medtronic", "medtronic", 1, "MedtronicCareers"),
    ("Micron", "micron", 1, "External"),
    ("Motorola Solutions", "motorolasolutions", 5, "Careers"),
    ("NXP", "nxp", 3, "Careers"),
    ("Old Dominion", "odfl", 1, "Odfl_Careers"),
    ("PPG", "ppg", 5, "Ppg_Careers"),
    ("Qualcomm", "qualcomm", 12, "External"),
    ("Qualys", "qualys", 5, "Careers"),
    ("Raymond James", "raymondjames", 1, "RaymondjamesCareers"),
    ("Regeneron", "regeneron", 1, "Careers"),
    ("RingCentral", "ringcentral", 1, "Ringcentral_Careers"),
    ("Stryker", "stryker", 1, "StrykerCareers"),
    ("TJX", "tjx", 1, "Tjx_External"),
    ("Tapestry", "tapestry", 108, "Tapestry_Careers"),
    ("Thermo Fisher", "thermofisher", 5, "ThermofisherCareers"),
    ("Trimble", "trimble", 1, "TrimbleCareers"),
    ("Unisys", "unisys", 5, "External"),
    ("Unum", "unum", 1, "External"),
    ("Walmart", "walmart", 5, "External"),
    ("Williams", "williams", 5, "External"),
    ("Xcel Energy", "xcelenergy", 1, "External"),

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

    # ── $1B+ employers (verified HTTP 200 from droplet 2026-06-24) ──────────
    ("10x Genomics", "10xgenomics"),
    ("2U", "2u"),
    ("Amplitude", "amplitude"),
    ("Anthropic", "anthropic"),
    ("Asana", "asana"),
    ("Astranis", "astranis"),
    ("Attentive", "attentive"),
    ("Aurora", "aurorainnovation"),
    ("Bill.com", "billcom"),
    ("Branch", "branchmetrics"),
    ("Braze", "braze"),
    ("C3.ai", "c3iot"),
    ("Calendly", "calendly"),
    ("Calm", "calm"),
    ("Carta", "carta"),
    ("Carvana", "carvana"),
    ("Celonis", "celonis"),
    ("Checkr", "checkr"),
    ("ClassPass", "classpass"),
    ("ClickHouse", "clickhouse"),
    ("Cockroach Labs", "cockroachlabs"),
    ("Compass", "urbancompass"),
    ("Coupang", "coupang"),
    ("Coursera", "coursera"),
    ("Culture Amp", "cultureamp"),
    ("DoubleVerify", "doubleverify"),
    ("Duolingo", "duolingo"),
    ("Faire", "faire"),
    ("FanDuel", "fanduel"),
    ("Fivetran", "fivetran"),
    ("Flatiron Health", "flatironhealth"),
    ("Ginkgo Bioworks", "ginkgobioworks"),
    ("Glossier", "glossier"),
    ("Grafana Labs", "grafanalabs"),
    ("Greenhouse Software", "greenhouse"),
    ("Guild", "guild"),
    ("Gusto", "gusto"),
    ("Imply", "imply"),
    ("Iterable", "iterable"),
    ("JFrog", "jfrog"),
    ("Klaviyo", "klaviyo"),
    ("Komodo Health", "komodohealth"),
    ("Lattice", "lattice"),
    ("Lucid Motors", "lucidmotors"),
    ("Mixpanel", "mixpanel"),
    ("Natera", "natera"),
    ("New Relic", "newrelic"),
    ("Nubank", "nubank"),
    ("Nuro", "nuro"),
    ("Oura", "oura"),
    ("PagerDuty", "pagerduty"),
    ("Planet Labs", "planetlabs"),
    ("Postman", "postman"),
    ("Recursion", "recursionpharmaceuticals"),
    ("SeatGeek", "seatgeek"),
    ("Sigma Computing", "sigmacomputing"),
    ("Smartsheet", "smartsheet"),
    ("Sumo Logic", "sumologic"),
    ("Temporal", "temporaltechnologies"),
    ("Udemy", "udemy"),
    ("Unity Technologies", "unity3d"),
    ("Upstart", "upstart"),
    ("Vercel", "vercel"),
    ("Via", "via"),
    ("Wayve", "wayve"),
    ("Webflow", "webflow"),

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
    if not is_corporate_role(t):
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
    'Posted 3 Days Ago', 'Posted 30+ Days Ago', 'Posted 2 Hours Ago', etc.)
    into a UTC datetime. Returns None when the string can't be parsed."""
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
    # ISO fallback (some ATSs use this)
    return parse_iso(t)


def parse_iso(text: str) -> "datetime | None":
    """Parse an ISO 8601 timestamp; return UTC datetime or None."""
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


def first_truthy_date(*candidates: "datetime | None") -> "datetime | None":
    """Return the first non-None datetime from the candidates."""
    for c in candidates:
        if c is not None:
            return c
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
        # first_published = actual posting time. updated_at = last recruiter
        # touch (could be a refresh of an old listing). Prefer the former so
        # the 2-day window is honored against true posting age.
        posted_dt = first_truthy_date(
            parse_iso(job.get("first_published") or ""),
            parse_iso(job.get("published_at") or ""),
            parse_iso(job.get("created_at") or ""),
            parse_iso(job.get("updated_at") or ""),
        )
        if not within_recency(posted_dt):
            continue
        label = ""
        if posted_dt:
            label = posted_dt.date().isoformat()
        found.append(make_job(
            company=name, title=title, url=job.get("absolute_url", ""),
            city=city, location=location, source="greenhouse-finance",
            posted_dt=posted_dt, posted_label=label,
        ))
    return found


def scrape_citi_rss():
    """Citi publishes its entire job board as an RSS feed (~4k entries).
    Filter to entry-level finance + supported cities + 2-day window."""
    name = "Citigroup"
    url = "https://jobs.citi.com/rss/jobs"
    try:
        resp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
        if resp.status_code != 200:
            print(f"  [{name}] HTTP {resp.status_code}")
            return []
        root = ET.fromstring(resp.content)
    except Exception as exc:
        print(f"  [{name}] error: {exc}")
        return []
    found = []
    for item in root.findall(".//item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        # Citi RSS titles look like "Foo Analyst - (New York, NY, United States)".
        # Split title from location.
        m = re.match(r"^(.*?)\s*-\s*\((.+)\)\s*$", raw_title)
        if m:
            title, location = m.group(1).strip(), m.group(2).strip()
        else:
            title, location = raw_title, ""
        if not title_is_finance_entry(title):
            continue
        city = infer_city(location)
        if not city:
            continue
        posted_dt = None
        if pub:
            try:
                dt = parsedate_to_datetime(pub)
                if dt:
                    posted_dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                posted_dt = None
        if not within_recency(posted_dt):
            continue
        found.append(make_job(
            company=name, title=title, url=link, city=city,
            location=location, source="citi-rss",
            posted_dt=posted_dt,
            posted_label=posted_dt.date().isoformat() if posted_dt else "",
        ))
    return found


def _playwright_companies(pw_page):
    """Wrap the JS-rendered employers (JPMorgan, Goldman) so Playwright failures
    on one don't kill the others. Returns the union of scraped jobs."""
    out = []
    try:
        out.extend(scrape_jpmorgan_pw(pw_page))
    except Exception as exc:
        print(f"  [JPMorgan] playwright error: {exc}")
    try:
        out.extend(scrape_goldman_pw(pw_page))
    except Exception as exc:
        print(f"  [Goldman] playwright error: {exc}")
    return out


def scrape_jpmorgan_pw(page):
    """JPMorgan careers.jpmorgan.com is a React SPA — render in headless
    browser and scrape the resulting DOM."""
    from bs4 import BeautifulSoup
    name = "JPMorgan Chase"
    candidates = []
    for term in ("financial analyst", "investment banking", "audit", "associate"):
        url = (
            "https://careers.jpmorgan.com/US/en/jobs"
            f"?search={urllib.parse.quote(term)}&location=New+York"
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(5000)
        except Exception as exc:
            print(f"  [{name}/{term}] goto error: {exc}")
            continue
        soup = BeautifulSoup(page.content(), "html.parser")
        for card in soup.select("[data-job-id], .job-listing, [class*='job-card'], [class*='requisition']"):
            title_el = card.find("h2") or card.find("h3") or card.find(class_=re.compile(r"title|heading", re.I))
            link_el = card.find("a", href=True)
            loc_el = card.find(class_=re.compile(r"location|city", re.I))
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            location = loc_el.get_text(strip=True) if loc_el else ""
            href = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = "https://careers.jpmorgan.com" + href
            if not title_is_finance_entry(title):
                continue
            city = infer_city(location or title)
            if not city:
                continue
            # No reliable per-card posted date on JPM's listing — accept; the
            # dashboard layer's 2-day cutoff acts on found_at as a backstop.
            candidates.append(make_job(
                company=name, title=title, url=href, city=city,
                location=location, source="playwright-jpmc",
                posted_dt=datetime.now(timezone.utc),
                posted_label=datetime.now(timezone.utc).date().isoformat(),
            ))
        time.sleep(1.5)
    print(f"  [{name}] {len(candidates)} candidate(s)")
    return candidates


def scrape_goldman_pw(page):
    """Goldman higher.gs.com is a React SPA — same approach as JPMorgan."""
    from bs4 import BeautifulSoup
    name = "Goldman Sachs"
    candidates = []
    for term in ("financial analyst", "investment banking analyst", "research analyst", "audit"):
        url = f"https://higher.gs.com/roles?query={urllib.parse.quote(term)}&region=Americas"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(4000)
        except Exception as exc:
            print(f"  [{name}/{term}] goto error: {exc}")
            continue
        soup = BeautifulSoup(page.content(), "html.parser")
        for link_el in soup.select("a[href*='/roles/']"):
            full_text = link_el.get_text(separator=" ", strip=True)
            href = link_el["href"]
            if not href.startswith("http"):
                href = "https://higher.gs.com" + href
            title = full_text
            location = ""
            for loc_kw in ("New York", "Jersey City", "NYC"):
                if loc_kw in full_text:
                    idx = full_text.index(loc_kw)
                    title = full_text[:idx].strip().rstrip("-,·").strip()
                    location = full_text[idx:]
                    break
            if not title_is_finance_entry(title):
                continue
            city = infer_city(location or full_text)
            if not city:
                continue
            candidates.append(make_job(
                company=name, title=title, url=href, city=city,
                location=location or "New York, NY",
                source="playwright-goldman",
                posted_dt=datetime.now(timezone.utc),
                posted_label=datetime.now(timezone.utc).date().isoformat(),
            ))
        time.sleep(1.5)
    print(f"  [{name}] {len(candidates)} candidate(s)")
    return candidates


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

    print("[Citi] RSS…")
    all_jobs.extend(scrape_citi_rss())

    # Regional employers on non-Workday/Greenhouse platforms (Oracle, Lever,
    # Phenom, iCIMS, SuccessFactors) — the only way to reach the PA/MD local
    # employers (Armstrong, WellSpan, Fulton, Dentsply, Hershey, …).
    print("[Extra ATS] Oracle/Lever/Phenom/iCIMS/SuccessFactors…")
    all_jobs.extend(collect_extra_jobs(
        title_filter=title_is_finance_entry,
        infer_city=infer_city,
        within_recency=within_recency,
        make_job=make_job,
        source_suffix="finance",
    ))

    # JS-rendered sites need Playwright. Isolate so a single browser failure
    # doesn't lose the rest of today's data.
    try:
        from playwright.sync_api import sync_playwright
        print("[Playwright] launching Chromium for JPMorgan + Goldman…")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                pw_page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36")
                all_jobs.extend(_playwright_companies(pw_page))
            finally:
                browser.close()
    except Exception as exc:
        print(f"[Playwright] block failed entirely: {exc}")

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
