#!/usr/bin/env python3
"""
Jordan's Job Finder — Expanded Multi-Company Scraper
-----------------------------------------------------
Cities   : NYC (VP only) | Atlanta (VP or Senior)
Finance  : Top 500 finance + hedge funds with NYC / Atlanta presence
Tech     : Top 100 tech companies with NYC / Atlanta offices
Output   : /var/www/jordansjobfinder/jobs.html
Cron     : daily at 12:00 PM
"""

import json, re, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
SEEN_FILE   = SCRIPT_DIR / "seen_jobs.json"
OUTPUT_FILE = SCRIPT_DIR / "jobs.html"
LOG_FILE    = SCRIPT_DIR / "scraper.log"
STORE_FILE  = SCRIPT_DIR / "jobs_store.json"

# ── Filters ───────────────────────────────────────────────────────────────────
TARGET_ROLES      = ["product manager", "program manager",
                     "product management", "program management"]
VP_TERMS          = [r"\bvice president\b", r"\b vp\b", r"\bvp,", r"\(vp\)"]
SENIOR_TERMS      = [r"\bsenior\b", r"\bsr\b", r"\blead\b",
                     r"\bstaff\b", r"\bprincipal\b"]
EXCLUDE_SENIORITY = [r"senior vice", r"assistant vice", r"\bavp\b", r"\bsvp\b",
                     r"\bdirector\b", r"\bmanaging director\b"]

NYC_LOCS     = ["new york", "nyc", "manhattan", "brooklyn", "jersey city"]
ATLANTA_LOCS = ["atlanta", "alpharetta", "buckhead", "sandy springs",
                "dunwoody", "midtown", "ga,", ", ga", "georgia"]

MIN_SALARY   = 180_000
VALID_POST_DAYS = 2
TECH_THRESHOLD  = 3
TECH_SIGNALS = [
    "agile", "scrum", "sprint", "api", "cloud", "aws", "azure", "gcp",
    "engineering", "software", "infrastructure", "platform", "microservices",
    "machine learning", "artificial intelligence", " ai ", "devops",
    "kubernetes", "docker", "ci/cd", "data pipeline", "architecture",
    "roadmap", "tech stack", "jira", "confluence", "technical",
    "technology", "digital transformation", "system design",
    "backend", "frontend", "data", "analytics", "fintech", "payments",
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}

# ── Company Configs ────────────────────────────────────────────────────────────
# (name, tenant, workday_ver, site_name, city)
# city: "nyc" | "atlanta"
WORKDAY_COMPANIES = [
    # ── Finance · NYC ──────────────────────────────────────────────────────────
    ("TIAA",             "tiaa",          1,   "Search",                  "nyc"),
    ("Travelers",        "travelers",     5,   "External",                "nyc"),
    ("Wells Fargo",      "wf",            1,   "WellsFargoJobs",          "nyc"),
    ("Bank of America",  "ghr",           1,   "Lateral-US",              "nyc"),
    ("Morgan Stanley",   "ms",            5,   "External",                "nyc"),
    ("BlackRock",        "blackrock",     1,   "BlackRock_Professional",  "nyc"),
    ("Vanguard",         "vanguard",      5,   "vanguard_external",       "nyc"),
    ("Fidelity",         "fmr",           1,   "FidelityCareers",         "nyc"),
    ("State Street",     "statestreet",   1,   "Global",                  "nyc"),
    ("T. Rowe Price",    "troweprice",    5,   "TRowePrice",              "nyc"),
    ("Prudential",       "pru",           5,   "Careers",                 "nyc"),
    ("AIG",              "aig",           1,   "aig",                     "nyc"),
    ("The Hartford",     "thehartford",   5,   "Careers_External",        "nyc"),
    ("Allstate",         "allstate",      5,   "allstate_careers",        "nyc"),
    ("Nationwide",       "nationwide",    1,   "Nationwide_Career",       "nyc"),
    ("Mastercard",       "mastercard",    1,   "CorporateCareers",        "nyc"),
    ("S&P Global",       "spgi",          5,   "SPGI_Careers",            "nyc"),
    ("Nasdaq",           "nasdaq",        1,   "US_External_Career_Site", "nyc"),
    ("CME Group",        "cmegroup",      1,   "cme_careers",             "nyc"),
    ("Blackstone",       "blackstone",    1,   "Blackstone_Careers",      "nyc"),
    ("Apollo",           "athene",        5,   "Apollo_Careers",          "nyc"),
    ("Millennium Mgmt",  "mlp",           5,   "mlpcareers",              "nyc"),
    ("FactSet",          "factset",       108, "FactSetCareers",          "nyc"),
    # ── Tech · NYC ─────────────────────────────────────────────────────────────
    ("Netflix",          "netflix",       1,   "Netflix",                 "nyc"),
    ("Salesforce",       "salesforce",    12,  "External_Career_Site",    "nyc"),
    ("Etsy",             "etsy",          5,   "Etsy_Careers",            "nyc"),
    ("Snap",             "snapchat",      1,   "snap",                    "nyc"),
    # ── Finance · Atlanta ──────────────────────────────────────────────────────
    ("Equifax",          "equifax",       1,   "equifax",                 "atlanta"),
    ("Global Payments",  "globalpayments",5,   "GPExternalCareers",       "atlanta"),
    ("Fiserv",           "fiserv",        5,   "fiserv",                  "atlanta"),
    ("Millennium Mgt ATL","mlp",          5,   "mlpcareers",              "atlanta"),
    ("S&P Global ATL",   "spgi",          5,   "SPGI_Careers",            "atlanta"),
    # ── Tech & Corporate · Atlanta ─────────────────────────────────────────────
    ("Delta Air Lines",  "delta",         5,   "Delta_External_Careers",  "atlanta"),
    ("Home Depot",       "ext",           5,   "HomeDepotExternalCareers","atlanta"),
    ("NCR Voyix",        "ncrvoyix",      5,   "NCRVoyixCareers",         "atlanta"),
    ("Norfolk Southern", "nssouthern",    1,   "NSCareers",               "atlanta"),
    ("UPS",              "ups",           5,   "UPS_External_Career_Site","atlanta"),
    ("Southern Company", "southerncompany",1,  "SoCo_External",           "atlanta"),
    ("Manhattan Assoc",  "mas",           5,   "MASCareers",              "atlanta"),
    ("Cox Enterprises",  "coxenterprises",5,   "CoxCareers",              "atlanta"),
    ("Genuine Parts",    "genuineparts",  1,   "GPC",                     "atlanta"),
    ("Salesforce ATL",   "salesforce",    12,  "External_Career_Site",    "atlanta"),
    ("NCR Atleos",       "ncratleos",     5,   "NCRAtleosCareers",        "atlanta"),
    # ── Finance · NYC (new) ────────────────────────────────────────────────────
    ("Deutsche Bank",    "db",            1,   "DBmanagement",            "nyc"),
    ("Barclays",         "barclays",      5,   "Barclays",                "nyc"),
    ("UBS",              "ubs",           1,   "UBS_Global",              "nyc"),
    ("BNY Mellon",       "bnymellon",     5,   "BNY_Mellon_Careers",      "nyc"),
    ("HSBC",             "hsbc",          5,   "HSBCCareer",              "nyc"),
    ("Nomura",           "nomura",        5,   "Nomura",                  "nyc"),
    ("Jefferies",        "jefferies",     5,   "Jefferies",               "nyc"),
    ("Ally Financial",   "ally",          5,   "ally",                    "nyc"),
    ("Citadel",          "citadel",       5,   "Citadel",                 "nyc"),
    ("D.E. Shaw",        "deshaw",        5,   "External",                "nyc"),
    ("Jane Street",      "janestreet",    5,   "External",                "nyc"),
    # ── Tech · NYC (new) ───────────────────────────────────────────────────────
    ("Microsoft",        "microsoftcareers", 5, "MicrosoftCareers",       "nyc"),
    ("Visa",             "visa",          5,   "Visa",                    "nyc"),
    ("PayPal",           "paypal",        5,   "paypal",                  "nyc"),
    ("Uber",             "uber",          5,   "External",                "nyc"),
    ("Spotify",          "spotify",       5,   "External",                "nyc"),
    ("ByteDance",        "bytedance",     5,   "External",                "nyc"),
    ("Workday Inc",      "workday",       5,   "workday",                 "nyc"),
    ("Plaid",            "plaid",         5,   "External",                "nyc"),
    # ── Enterprise · NYC + Atlanta (new) ───────────────────────────────────────
    ("IBM",              "ibm",           5,   "External",                "nyc"),
    ("Accenture",        "accenture",     5,   "AccentureCareers",        "nyc"),
    ("SAP",              "sap",           5,   "SAP",                     "nyc"),
    ("Oracle",           "oracle",        5,   "oracle",                  "nyc"),
    ("ServiceNow",       "servicenow",    5,   "External",                "nyc"),
    ("IBM ATL",          "ibm",           5,   "External",                "atlanta"),
    ("Accenture ATL",    "accenture",     5,   "AccentureCareers",        "atlanta"),
    ("SAP ATL",          "sap",           5,   "SAP",                     "atlanta"),
    ("Oracle ATL",       "oracle",        5,   "oracle",                  "atlanta"),
    ("ServiceNow ATL",   "servicenow",    5,   "External",                "atlanta"),
    # ── Finance & Corporate · Atlanta (new) ────────────────────────────────────
    ("ICE",              "ice",           5,   "ice",                     "atlanta"),
    ("Honeywell",        "honeywell",     5,   "Honeywell",               "atlanta"),
    ("Elevance Health",  "elevancehealth",5,   "External",                "atlanta"),
    ("Roper Tech",       "roper",         5,   "External",                "atlanta"),
    ("Chick-fil-A",      "cfacorp",       5,   "CFA_External",            "atlanta"),
    ("Porsche Cars NA",  "porschecars",   5,   "External",                "atlanta"),
    ("Inspire Brands",   "inspirebrands", 5,   "External",                "atlanta"),
]

# (name, greenhouse_token, city)
GREENHOUSE_COMPANIES = [
    # Finance · NYC
    ("KKR",           "kkrcareers",    "nyc"),
    ("Bridgewater",   "bridgewater89", "nyc"),
    ("Point72",       "point72",       "nyc"),
    ("AQR Capital",   "aqr",           "nyc"),
    # Tech · NYC
    ("MongoDB",       "mongodb",       "nyc"),
    ("Datadog",       "datadog",       "nyc"),
    ("Squarespace",   "squarespace",   "nyc"),
    ("DoorDash",      "doordashusa",   "nyc"),
    ("Airbnb",        "airbnb",        "nyc"),
    ("Pinterest",     "pinterest",     "nyc"),
    ("Peloton",       "peloton",       "nyc"),
    # Tech · Atlanta
    ("Cardlytics",    "cardlytics-2",  "atlanta"),
    ("SecureWorks",   "secureworksinc","atlanta"),
    ("Cox Enterprises GH", "coxenterprises", "atlanta"),
    # Finance · NYC (new)
    ("Robinhood",     "robinhood",     "nyc"),
    ("Lone Pine Cap", "lonepinecapital","nyc"),
    # Tech · NYC (new)
    ("Stripe",        "stripe",        "nyc"),
    ("Adyen",         "adyen",         "nyc"),
    ("Brex",          "brex",          "nyc"),
    ("Marqeta",       "marqeta",       "nyc"),
    ("Lyft",          "lyft",          "nyc"),
    ("SoFi",          "sofi",          "nyc"),
    ("LinkedIn",      "linkedin",      "nyc"),
]

# (name, lever_token, city)
LEVER_COMPANIES = [
    ("Palantir",   "palantir",         "nyc"),
]

# Eightfold: (name, domain, base_url, city)
EIGHTFOLD_COMPANIES = [
    ("American Express", "aexp", "https://aexp.eightfold.ai/careers/job", "nyc"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def load_store():
    if STORE_FILE.exists():
        return json.loads(STORE_FILE.read_text())
    return []


def save_store(store):
    STORE_FILE.write_text(json.dumps(store, indent=2))


def purge_old_store(store):
    cutoff = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
    kept = []
    for job in store:
        try:
            found_at = datetime.fromisoformat(job.get("found_at", ""))
            if found_at.tzinfo is None:
                found_at = found_at.replace(tzinfo=timezone.utc)
            if found_at >= cutoff:
                kept.append(job)
        except Exception:
            kept.append(job)
    return kept


def is_vp(title):
    t = title.lower()
    if any(re.search(p, t) for p in EXCLUDE_SENIORITY):
        return False
    return any(re.search(p, t) for p in VP_TERMS)


def is_senior(title):
    t = title.lower()
    return any(re.search(p, t) for p in SENIOR_TERMS)


def level_ok(title, city):
    """VP required for NYC; VP or Senior for Atlanta."""
    return is_vp(title) if city == "nyc" else (is_vp(title) or is_senior(title))


def is_target_role(title):
    t = title.lower()
    return any(r in t for r in TARGET_ROLES)


def is_nyc(text):
    t = text.lower()
    return any(loc in t for loc in NYC_LOCS)


def is_atlanta(text):
    t = text.lower()
    return any(loc in t for loc in ATLANTA_LOCS)


def location_ok(text, city):
    return is_nyc(text) if city == "nyc" else is_atlanta(text)


def is_recent_rfc(pub_date_str):
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
        return pub_dt >= cutoff
    except Exception:
        return False


def is_recent_iso(date_str):
    if not date_str:
        return False
    try:
        for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                ds = date_str.strip()
                if fmt == "%Y-%m-%dT%H:%M:%S%z":
                    dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
                    cutoff = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
                    return dt.replace(tzinfo=timezone.utc) >= cutoff
                dt = datetime.strptime(ds[:10], "%Y-%m-%d") if fmt == "%Y-%m-%d" else datetime.strptime(ds, fmt)
                cutoff = datetime.now() - timedelta(days=VALID_POST_DAYS)
                return dt >= cutoff
            except ValueError:
                continue
    except Exception:
        pass
    return False


def parse_salary(text):
    nums = [int(n.replace(",", "")) for n in re.findall(r"[\d,]+", text.replace(".00", ""))
            if int(n.replace(",", "")) >= 50_000]
    if len(nums) >= 2:
        return min(nums), max(nums)
    if len(nums) == 1:
        return nums[0], nums[0]
    return None


def salary_ok(salary_text):
    result = parse_salary(salary_text)
    if not result:
        return False
    _, max_sal = result
    return max_sal >= MIN_SALARY


def is_tech(description):
    desc = description.lower()
    return sum(1 for kw in TECH_SIGNALS if kw in desc) >= TECH_THRESHOLD


def make_job(title, url, company, city, salary="", posted="Unknown", location=""):
    return dict(title=title, url=url, company=company, city=city,
                salary=salary, posted=posted, location=location)


# ── Playwright detail fetcher ──────────────────────────────────────────────────

def fetch_detail(page, url):
    """Return (salary_text, full_text, posted_str)."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2000)
        # Accept cookie consent if present (Workday / other sites)
        for sel in ["button[data-automation-id='acceptAllButton']",
                    "button:has-text('Accept')", "button:has-text('Accept Cookies')",
                    "#onetrust-accept-btn-handler"]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                pass
    except Exception:
        return "", "", ""

    soup      = BeautifulSoup(page.content(), "html.parser")
    full_text = soup.get_text(separator=" ", strip=True)

    # Salary: only match amounts that look like annual compensation ($50k+)
    salary_m = re.findall(
        r"\$\s*(\d{1,3}(?:,\d{3})+)(?:\s*[-–to]+\s*\$\s*(\d{1,3}(?:,\d{3})+))?",
        full_text)
    salary = ""
    for match in salary_m:
        low = int(match[0].replace(",", ""))
        high = int(match[1].replace(",", "")) if match[1] else low
        if high >= 50_000:
            salary = f"${match[0]}" + (f" – ${match[1]}" if match[1] else "")
            break

    date_m = re.search(r"[Pp]osted[:\s]+([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})", full_text)
    posted = date_m.group(1).strip() if date_m else "Unknown"

    return salary, full_text, posted


# ══════════════════════════════════════════════════════════════════════════════
#  SCRAPERS
# ══════════════════════════════════════════════════════════════════════════════

# ── Citigroup — TalentBrew RSS ─────────────────────────────────────────────────

def scrape_citi():
    log("  [Citigroup] Fetching RSS feed...")
    try:
        req = urllib.request.Request(
            "https://jobs.citi.com/rss/jobs",
            headers={"User-Agent": HEADERS["User-Agent"]}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        log(f"    Error: {e}")
        return []

    candidates = []
    for item in root.findall(".//item"):
        title    = item.findtext("title") or ""
        url      = item.findtext("link")  or ""
        pub_date = item.findtext("pubDate") or ""
        if not (is_nyc(title) and is_target_role(title) and is_vp(title)
                and is_recent_rfc(pub_date)):
            continue
        candidates.append(make_job(
            title=title.split(" - (")[0].strip(),
            url=url, company="Citigroup", city="nyc", posted=pub_date
        ))
    log(f"  [Citigroup] {len(candidates)} candidate(s)")
    return candidates


# ── Generic Workday API ────────────────────────────────────────────────────────

def scrape_workday_company(name, tenant, wd_ver, site, city):
    api = (f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com"
           f"/wday/cxs/{tenant}/{site}/jobs")
    candidates = []

    for term in ["product manager", "program manager"]:
        offset = 0
        while True:
            try:
                resp = requests.post(api,
                    json={"appliedFacets": {}, "limit": 20,
                          "offset": offset, "searchText": term},
                    headers={"Content-Type": "application/json",
                             "User-Agent": HEADERS["User-Agent"]},
                    timeout=15)
                if resp.status_code != 200:
                    break
                data = resp.json()
            except Exception as e:
                log(f"    [{name}] Error: {e}")
                break

            postings = data.get("jobPostings", [])
            total    = data.get("total", 0)

            for job in postings:
                title    = job.get("title", "")
                ext_path = job.get("externalPath", "")
                location = job.get("locationsText", "")
                posted   = job.get("postedOn", "")

                if not (is_target_role(title) and level_ok(title, city)):
                    continue
                loc_check = location or title
                if not location_ok(loc_check, city):
                    continue

                url = (f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com"
                       f"/en-US/{site}{ext_path}")
                candidates.append(make_job(
                    title=title, url=url, company=name, city=city,
                    posted=posted, location=location
                ))

            offset += 20
            if offset >= total or not postings:
                break
            time.sleep(0.5)

    return candidates


# ── Generic Greenhouse API ─────────────────────────────────────────────────────

def scrape_greenhouse_company(name, token, city):
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log(f"    [{name}] Greenhouse {resp.status_code}")
            return []
        jobs = resp.json().get("jobs", [])
    except Exception as e:
        log(f"    [{name}] Error: {e}")
        return []

    candidates = []
    for job in jobs:
        title    = job.get("title", "")
        location = job.get("location", {}).get("name", "")
        job_url  = job.get("absolute_url", "")
        updated  = job.get("updated_at", "")[:10]
        content  = BeautifulSoup(job.get("content", ""), "html.parser").get_text(" ")

        if not (is_target_role(title) and level_ok(title, city)):
            continue
        if not location_ok(location or content[:500], city):
            continue
        if updated and not is_recent_iso(updated):
            continue

        candidates.append(make_job(
            title=title, url=job_url, company=name, city=city,
            posted=updated, location=location
        ))

    return candidates


# ── Generic Lever API ──────────────────────────────────────────────────────────

def scrape_lever_company(name, token, city):
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log(f"    [{name}] Lever {resp.status_code}")
            return []
        postings = resp.json()
    except Exception as e:
        log(f"    [{name}] Error: {e}")
        return []

    candidates = []
    for job in postings:
        title     = job.get("text", "")
        location  = job.get("categories", {}).get("location", "")
        job_url   = job.get("hostedUrl", "")
        created   = job.get("createdAt", 0)
        desc_text = job.get("descriptionPlain", "") or ""

        if not (is_target_role(title) and level_ok(title, city)):
            continue
        if not location_ok(location or desc_text[:500], city):
            continue
        # created is Unix ms
        try:
            post_dt = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            cutoff  = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
            if post_dt < cutoff:
                continue
        except Exception:
            pass

        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if created else ""
        candidates.append(make_job(
            title=title, url=job_url, company=name, city=city,
            posted=posted, location=location
        ))

    return candidates


# ── Generic Eightfold API ──────────────────────────────────────────────────────

def scrape_eightfold_company(name, domain, base_url, city):
    loc_query = "New York" if city == "nyc" else "Atlanta"
    candidates = []

    for term in ["product manager", "program manager"]:
        try:
            resp = requests.get(
                f"https://{domain}.eightfold.ai/api/apply/v2/jobs",
                params={"domain": f"{domain}.com", "query": term,
                        "location": loc_query, "count": 50, "page": 1},
                headers=HEADERS, timeout=15)
            jobs = resp.json().get("positions", [])
        except Exception as e:
            log(f"    [{name}] Error: {e}")
            continue

        for job in jobs:
            title    = job.get("name", "")
            job_id   = job.get("id", "")
            location = job.get("location", "")
            t_create = job.get("t_create")
            try:
                posted = datetime.fromtimestamp(int(t_create), tz=timezone.utc).strftime("%Y-%m-%d") if t_create else ""
            except Exception:
                posted = ""

            if not (is_target_role(title) and level_ok(title, city)):
                continue
            if not location_ok(location, city):
                continue
            if posted and not is_recent_iso(posted):
                continue

            url = f"{base_url}/{job_id}"
            candidates.append(make_job(
                title=title, url=url, company=name, city=city,
                posted=posted, location=location
            ))
        time.sleep(1)

    return candidates


# ── JPMorgan Chase — Playwright ────────────────────────────────────────────────

def scrape_jpmorgan(page):
    log("  [JPMorgan Chase] Playwright...")
    candidates = []
    for term in ["product manager", "program manager"]:
        url = (f"https://careers.jpmorgan.com/US/en/jobs"
               f"?search={urllib.parse.quote(term)}&location=New+York&lob=Technology")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(5000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for card in soup.select("[data-job-id], .job-listing, [class*='job-card'], [class*='requisition']"):
            title_el = card.find("h2") or card.find("h3") or card.find(class_=re.compile(r"title|heading", re.I))
            link_el  = card.find("a", href=True)
            loc_el   = card.find(class_=re.compile(r"location|city", re.I))
            if not title_el:
                continue
            title    = title_el.get_text(strip=True)
            location = loc_el.get_text(strip=True) if loc_el else ""
            href     = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = "https://careers.jpmorgan.com" + href
            if not (is_target_role(title) and is_vp(title) and is_nyc(location or title)):
                continue
            candidates.append(make_job(title=title, url=href,
                                       company="JPMorgan Chase", city="nyc", location=location))
        time.sleep(2)
    log(f"  [JPMorgan Chase] {len(candidates)} candidate(s)")
    return candidates


# ── Goldman Sachs — Playwright ─────────────────────────────────────────────────

def scrape_goldman(page):
    log("  [Goldman Sachs] Playwright...")
    candidates = []
    for term in ["product manager", "program manager"]:
        url = f"https://higher.gs.com/roles?query={urllib.parse.quote(term)}&region=Americas"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(4000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for link_el in soup.select("a[href*='/roles/']"):
            full_text = link_el.get_text(separator=" ", strip=True)
            href      = link_el["href"]
            if not href.startswith("http"):
                href = "https://higher.gs.com" + href

            title    = full_text
            location = ""
            for loc_kw in ["New York", "Jersey City", "NYC"]:
                if loc_kw in full_text:
                    idx      = full_text.index(loc_kw)
                    title    = full_text[:idx].strip().rstrip("-,·").strip()
                    location = full_text[idx:]
                    break

            if not (is_target_role(title) and is_vp(title)):
                continue
            if location and not is_nyc(location):
                continue
            if not location and not is_nyc(full_text):
                continue

            candidates.append(make_job(title=title, url=href,
                                       company="Goldman Sachs", city="nyc",
                                       location=location or "New York, NY"))
        time.sleep(2)
    log(f"  [Goldman Sachs] {len(candidates)} candidate(s)")
    return candidates


# ── MetLife — Playwright ───────────────────────────────────────────────────────

def scrape_metlife(page):
    log("  [MetLife] Playwright...")
    candidates = []
    for term in ["product manager", "program manager"]:
        url = f"https://www.metlifecareers.com/en_US/ml/SearchJobs/{urllib.parse.quote(term)}?3_118_3=8491"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(3000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for card in soup.select("[class*='job'], [class*='position'], li.result"):
            title_el = card.find("h2") or card.find("h3") or card.find(class_=re.compile(r"title", re.I))
            link_el  = card.find("a", href=True)
            loc_el   = card.find(class_=re.compile(r"location", re.I))
            if not title_el:
                continue
            title    = title_el.get_text(strip=True)
            location = loc_el.get_text(strip=True) if loc_el else ""
            href     = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = "https://www.metlifecareers.com" + href
            if not (is_nyc(location) and is_target_role(title) and is_vp(title)):
                continue
            candidates.append(make_job(title=title, url=href,
                                       company="MetLife", city="nyc", location=location))
        time.sleep(1)
    log(f"  [MetLife] {len(candidates)} candidate(s)")
    return candidates


# ── Google — Playwright ───────────────────────────────────────────────────────

def scrape_google(page, city="nyc"):
    log(f"  [Google] Playwright ({city})...")
    candidates = []
    loc_param  = "New+York%2C+NY" if city == "nyc" else "Atlanta%2C+GA"
    for term in ["product manager", "program manager"]:
        url = (f"https://www.google.com/about/careers/applications/jobs/results/"
               f"?q={urllib.parse.quote(term)}&location={loc_param}&employment_type=FULL_TIME")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(5000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for card in soup.select("li[class*='lLd3Je'], [jsmodel], [class*='job-result']"):
            title_el = card.find(class_=re.compile(r"title|heading|QJPWVe", re.I)) or card.find("h3")
            link_el  = card.find("a", href=True)
            loc_el   = card.find(class_=re.compile(r"location|r0wTof|NiZ4Mc", re.I))
            if not title_el:
                continue
            title    = title_el.get_text(strip=True)
            location = loc_el.get_text(strip=True) if loc_el else ""
            href     = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = "https://careers.google.com/" + href.lstrip("/")
            if not href or not href.startswith("http"):
                continue
            if not (is_target_role(title) and level_ok(title, city)):
                continue
            if not location_ok(location or url, city):
                continue
            candidates.append(make_job(title=title, url=href,
                                       company="Google", city=city, location=location))
        time.sleep(2)
    log(f"  [Google] {len(candidates)} candidate(s)")
    return candidates


# ── Meta — Playwright ─────────────────────────────────────────────────────────

def scrape_meta(page, city="nyc"):
    log(f"  [Meta] Playwright ({city})...")
    candidates = []
    loc_param  = "New+York%2C+NY" if city == "nyc" else "Atlanta%2C+GA"
    for term in ["product manager", "program manager"]:
        url = (f"https://www.metacareers.com/jobs?q={urllib.parse.quote(term)}"
               f"&offices[]={urllib.parse.quote('New York, NY' if city == 'nyc' else 'Atlanta, GA')}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(5000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for card in soup.select("[class*='_job'], [data-testid*='job'], a[href*='/jobs/']"):
            title_el = card.find(class_=re.compile(r"title|heading", re.I)) or card.find("span")
            link_el  = card if card.name == "a" else card.find("a", href=True)
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href  = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = "https://www.metacareers.com" + href
            if not (is_target_role(title) and level_ok(title, city)):
                continue
            candidates.append(make_job(title=title, url=href,
                                       company="Meta", city=city,
                                       location="New York, NY" if city == "nyc" else "Atlanta, GA"))
        time.sleep(2)
    log(f"  [Meta] {len(candidates)} candidate(s)")
    return candidates


# ── Amazon — JSON API ─────────────────────────────────────────────────────────

def scrape_amazon(city="nyc"):
    log(f"  [Amazon] API ({city})...")
    candidates = []
    loc = "New York,New York,United States" if city == "nyc" else "Atlanta,Georgia,United States"

    for term in ["product manager", "program manager"]:
        try:
            resp = requests.get(
                "https://www.amazon.jobs/en/search.json",
                params={"keywords": term, "normalized_location[]": loc,
                        "result_limit": 50, "offset": 0},
                headers={"User-Agent": HEADERS["User-Agent"],
                         "Accept": "application/json"},
                timeout=15)
            if resp.status_code != 200:
                continue
            jobs = resp.json().get("jobs", [])
        except Exception as e:
            log(f"    [Amazon] Error: {e}")
            continue

        for job in jobs:
            title    = job.get("title", "")
            location = job.get("location", "")
            job_url  = "https://www.amazon.jobs" + job.get("job_path", "")
            updated  = job.get("updated_time", "")[:10]

            if not (is_target_role(title) and level_ok(title, city)):
                continue
            if not location_ok(location, city):
                continue
            if updated and not is_recent_iso(updated):
                continue

            candidates.append(make_job(
                title=title, url=job_url, company="Amazon",
                city=city, posted=updated, location=location
            ))
        time.sleep(1)

    log(f"  [Amazon] {len(candidates)} candidate(s)")
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    log("=" * 60)
    log("Jordan's Job Finder — expanded multi-company scan")

    seen     = load_seen()
    new_jobs = []

    # ── Phase 1: No-browser scrapers ──────────────────────────────────────────
    all_candidates = []

    all_candidates += scrape_citi()

    for name, tenant, ver, site, city in WORKDAY_COMPANIES:
        log(f"  [{name}] Workday...")
        result = scrape_workday_company(name, tenant, ver, site, city)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    for name, token, city in GREENHOUSE_COMPANIES:
        log(f"  [{name}] Greenhouse...")
        result = scrape_greenhouse_company(name, token, city)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    for name, token, city in LEVER_COMPANIES:
        log(f"  [{name}] Lever...")
        result = scrape_lever_company(name, token, city)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    for name, domain, base_url, city in EIGHTFOLD_COMPANIES:
        log(f"  [{name}] Eightfold...")
        result = scrape_eightfold_company(name, domain, base_url, city)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    all_candidates += scrape_amazon("nyc")
    all_candidates += scrape_amazon("atlanta")

    # ── Phase 2: Playwright scrapers ──────────────────────────────────────────
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pw_page = browser.new_page(user_agent=HEADERS["User-Agent"])

        all_candidates += scrape_jpmorgan(pw_page)
        all_candidates += scrape_goldman(pw_page)
        all_candidates += scrape_metlife(pw_page)
        all_candidates += scrape_google(pw_page, "nyc")
        all_candidates += scrape_google(pw_page, "atlanta")
        all_candidates += scrape_meta(pw_page, "nyc")
        all_candidates += scrape_meta(pw_page, "atlanta")

        # ── Phase 3: Enrich candidates with detail page ───────────────────────
        log(f"Enriching {len(all_candidates)} candidates with detail pages...")

        for job in all_candidates:
            url = job["url"]
            if not url or url in seen:
                if url in seen:
                    log(f"  Skip duplicate: {job['title'][:55]}")
                continue

            log(f"  Detail: {job['company']} [{job['city'].upper()}] | {job['title'][:50]}")

            is_workday = "myworkdayjobs.com" in url

            if is_workday:
                # Workday pages are cookie-walled; use title-based tech check only
                if not is_tech(job["title"] + " product manager program manager technology"):
                    # Only fail if title has zero tech signal — VP PM at finance co is tech by default
                    pass  # include it
                if not job["salary"]:
                    job["salary"] = "See posting"
            else:
                salary, description, posted = fetch_detail(pw_page, url)
                if salary:
                    job["salary"] = salary
                if posted and posted != "Unknown":
                    job["posted"] = posted

                if job["salary"] and not salary_ok(job["salary"]):
                    log(f"    ✗ Salary too low: {job['salary']}")
                    continue
                if not job["salary"]:
                    job["salary"] = "See posting"

                if len(description) > 500:
                    if not is_tech(description):
                        log(f"    ✗ Not tech-focused")
                        continue
                else:
                    # Description didn't load — use title with lower threshold (2 signals)
                    title_lower = job["title"].lower()
                    tech_hits = sum(1 for kw in TECH_SIGNALS if kw in title_lower)
                    if tech_hits < 2:
                        log(f"    ✗ Not tech-focused (title only, {tech_hits} signals)")
                        continue
                time.sleep(1)

            log(f"    ✓ MATCH — {job['salary']} | {job['posted']}")
            new_jobs.append(job)
            seen.add(url)

        browser.close()

    # Persistent store: merge new jobs, purge old ones
    store = load_store()
    store = purge_old_store(store)
    store_urls = {j["url"] for j in store}
    now_iso = datetime.now(timezone.utc).isoformat()
    added = 0
    for job in new_jobs:
        if job["url"] and job["url"] not in store_urls:
            job["found_at"] = now_iso
            store.append(job)
            added += 1
    save_store(store)
    write_html(store)
    save_seen(seen)
    log(f"Done. {added} new job(s) added; {len(store)} total in store")


# ── HTML Output ───────────────────────────────────────────────────────────────

def write_html(jobs):
    run_date = datetime.now().strftime("%B %d, %Y — %I:%M %p")

    nyc_jobs = [j for j in jobs if j["city"] == "nyc"]
    atl_jobs = [j for j in jobs if j["city"] == "atlanta"]

    def make_cards(job_list, badge_color):
        if not job_list:
            return '<p class="none">No matching jobs found in the last 2 days.</p>'
        cards = ""
        for job in job_list:
            cards += f"""
        <div class="card">
          <div class="card-header">
            <span class="company">{job['company']}</span>
            <span class="posted">Posted: {job['posted']}</span>
          </div>
          <div class="title">{job['title']}</div>
          <div class="meta">
            <span class="salary">💰 {job['salary'] or 'Salary not listed'}</span>
            <span class="location">📍 {job['location'] or ('New York, NY' if job['city'] == 'nyc' else 'Atlanta, GA')}</span>
          </div>
          <a class="apply-btn" href="{job['url']}" target="_blank">View Job →</a>
        </div>"""
        return cards

    nyc_cards = make_cards(nyc_jobs, "#38bdf8")
    atl_cards = make_cards(atl_jobs, "#f97316")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jordan's Job Finder — {run_date}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f172a; color: #e2e8f0;
    padding: 32px 20px; max-width: 900px; margin: 0 auto;
  }}
  h1 {{ color: #38bdf8; font-size: 24px; margin-bottom: 4px; }}
  .subtitle {{ color: #64748b; font-size: 13px; margin-bottom: 32px; }}
  h2 {{ font-size: 16px; font-weight: 700; letter-spacing: 0.08em;
         text-transform: uppercase; margin: 28px 0 14px;
         padding-bottom: 8px; border-bottom: 1px solid #1e293b; }}
  h2.nyc {{ color: #38bdf8; }}
  h2.atl {{ color: #f97316; }}
  .card {{
    background: #1e293b; border-radius: 10px;
    padding: 20px 24px; margin-bottom: 14px;
    border-left: 4px solid #38bdf8;
  }}
  .card.atl {{ border-color: #f97316; }}
  .card:hover {{ filter: brightness(1.05); }}
  .card-header {{ display: flex; justify-content: space-between; margin-bottom: 8px; }}
  .company {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .posted  {{ color: #f97316; font-size: 12px; }}
  .title   {{ font-size: 17px; font-weight: 600; color: #f1f5f9; margin-bottom: 12px; line-height: 1.4; }}
  .meta    {{ display: flex; gap: 24px; margin-bottom: 16px; flex-wrap: wrap; }}
  .salary  {{ color: #4ade80; font-weight: 600; font-size: 14px; }}
  .location {{ color: #94a3b8; font-size: 14px; }}
  .apply-btn {{
    display: inline-block; background: #38bdf8; color: #0f172a;
    padding: 8px 18px; border-radius: 6px; text-decoration: none;
    font-weight: 700; font-size: 13px;
  }}
  .card.atl .apply-btn {{ background: #f97316; }}
  .apply-btn:hover {{ opacity: 0.85; }}
  .none {{ color: #64748b; font-style: italic; margin-top: 8px; }}
  .count {{ font-size: 12px; color: #64748b; margin-left: 8px; font-weight: normal; }}
</style>
</head>
<body>
  <h1>Jordan's Job Finder</h1>
  <p class="subtitle">
    Run: {run_date} &nbsp;·&nbsp; {len(nyc_jobs)} NYC job(s) &nbsp;·&nbsp; {len(atl_jobs)} Atlanta job(s)
  </p>

  <h2 class="nyc">🗽 New York City <span class="count">VP · Technical PM/PgM · $180k+</span></h2>
  {nyc_cards}

  <h2 class="atl">🍑 Atlanta <span class="count">VP or Senior · Technical PM/PgM</span></h2>
  {atl_cards}

</body>
</html>"""

    OUTPUT_FILE.write_text(html)


if __name__ == "__main__":
    main()
