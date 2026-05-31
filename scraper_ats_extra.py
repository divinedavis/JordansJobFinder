"""Extra ATS platforms beyond Workday + Greenhouse.

scraper_finance.py and scraper_sales.py natively scrape Workday and Greenhouse.
That misses the regional employers in the PA/MD metros (York, Lancaster,
Harrisburg, Philadelphia, Baltimore) whose careers sites run on other software:
Oracle Cloud Recruiting, Lever, Phenom (ex-iCIMS), iCIMS, and SuccessFactors.

This module adds one scraper per platform and exposes a single entry point,
`collect_extra_jobs()`, that both verticals call. Rather than re-declaring the
shared location map / recency window / make_job here (which would drift from the
two callers), the caller passes its own `title_filter`, `infer_city`,
`within_recency`, and `make_job` in — so this module stays the single home for
the *platform* logic while the *vertical* logic stays with each caller.

Every endpoint/identifier below was verified to return HTTP 200 with real job
data on 2026-05-31. See CLAUDE.md for the probe recipe before adding more.
"""
import json
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import requests

# SuccessFactors / iCIMS / Oracle reject the bot-ish UA the Workday path uses;
# they serve full HTML/JSON only to a browser-shaped User-Agent.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)
_H = {"User-Agent": BROWSER_UA}
_HJSON = {"User-Agent": BROWSER_UA, "Accept": "application/json"}

# --- Company registries (name + the bits each platform needs) -----------------
# Metro noted in a comment; actual placement is decided per-job by infer_city.

# Oracle Cloud Recruiting: (name, host, siteNumber). siteNumber format varies
# ("CX_1" vs "CX") — do not assume one universal value.
ORACLE_COMPANIES = [
    ("WellSpan Health",         "fa-evzu-saasfaprod1.fa.ocs.oraclecloud.com", "CX_1"),  # York
    ("Penn National Insurance", "efyb.fa.us6.oraclecloud.com",                "CX"),     # Harrisburg
]

# Lever: (name, handle)
LEVER_COMPANIES = [
    ("Gopuff", "gopuff"),  # Philadelphia
]

# Phenom (these companies' iCIMS subdomains now redirect to a Phenom site that
# exposes a clean JSON API): (name, base_url).
# DISABLED: jobs.exeloncorp.com / jobs.constellationenergy.com return HTTP 403
# to the production droplet's IP (Phenom's WAF blocks datacenter IPs) even with
# full browser headers, though they 200 from residential IPs. Re-enable only if
# the IP gets allowlisted. Philadelphia/Baltimore already have Workday coverage,
# so this is a no-op for those metros. The scrape_phenom() function is kept.
PHENOM_COMPANIES = [
    # ("Exelon",               "https://jobs.exeloncorp.com"),           # Philadelphia (403 from droplet)
    # ("Constellation Energy", "https://jobs.constellationenergy.com"),  # Phila/Baltimore (403 from droplet)
]

# True iCIMS HTML portals: (name, subdomain). The list + detail pages BOTH need
# &in_iframe=1 or they return a ~4 KB iframe stub with no jobs.
ICIMS_COMPANIES = [
    ("Fulton Bank",      "careers-fult"),             # Lancaster
    ("Graham Packaging", "careers-grahampackaging"),  # York
]

# SuccessFactors Career Site Builder: (name, host, page_size). page_size differs
# per site (Voith = 50, the rest = 25); stepping by the wrong size silently
# skips or double-counts rows.
SUCCESSFACTORS_COMPANIES = [
    ("Armstrong World Industries", "https://jobs.armstrong.com",            25),  # Lancaster
    ("Dentsply Sirona",            "https://careers.dentsplysirona.com",    25),  # York
    ("Voith",                      "https://jobs.voith.com",                50),  # York
    ("The Hershey Company",        "https://careers.thehersheycompany.com", 25),  # Harrisburg
    ("McCormick & Company",        "https://careers.mccormick.com",         25),  # Baltimore
]


# --- Date parsing -------------------------------------------------------------

def _parse_iso(text):
    """Parse ISO 8601 (incl. trailing Z, '+0000', and milliseconds) to UTC."""
    if not text:
        return None
    raw = text.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                dt = datetime.strptime(text.strip(), fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _parse_epoch_ms(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_sf_inline(text):
    """SuccessFactors list date, e.g. 'May 31, 2026'."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_sf_meta(text):
    """SuccessFactors detail <meta itemprop=datePosted>, e.g.
    'Sun May 31 02:00:00 UTC 2026'."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%a %b %d %H:%M:%S UTC %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# --- Platform scrapers --------------------------------------------------------

def scrape_oracle(ctx, name, host, site):
    """Oracle Cloud Recruiting public JSON API. Sorted newest-first, so the
    first 200 reqs always cover the 2-day window even on large boards."""
    url = (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        "?onlyData=true&expand=requisitionList.secondaryLocations,flexFieldsFacet.values"
        f"&finder=findReqs;siteNumber={site},limit=200,sortBy=POSTING_DATES_DESC"
    )
    r = requests.get(url, headers=_HJSON, timeout=25)
    if r.status_code != 200:
        print(f"  [{name}] HTTP {r.status_code}")
        return []
    items = r.json().get("items", [])
    reqs = items[0].get("requisitionList", []) if items else []
    found = []
    for req in reqs:
        title = req.get("Title", "")
        if not ctx.title_filter(title):
            continue
        primary = req.get("PrimaryLocation", "") or ""
        secondary = " ".join(s.get("Name", "") for s in (req.get("secondaryLocations") or []))
        city = ctx.infer_city(f"{primary} {secondary}")
        if not city:
            continue
        posted_dt = _parse_iso(req.get("PostedDate") or "")
        if not ctx.within_recency(posted_dt):
            continue
        jid = req.get("Id", "")
        jurl = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/requisitions/preview/{jid}"
        found.append(ctx.make_job(
            company=name, title=title, url=jurl, city=city, location=primary,
            source=ctx.source("oracle"), posted_dt=posted_dt,
            posted_label=req.get("PostedDate", "") or "",
        ))
    return found


def scrape_lever(ctx, name, handle):
    """Lever public postings API — full board in one JSON array."""
    r = requests.get(f"https://api.lever.co/v0/postings/{handle}?mode=json", headers=_H, timeout=25)
    if r.status_code != 200:
        print(f"  [{name}] HTTP {r.status_code}")
        return []
    found = []
    for post in r.json():
        title = post.get("text", "")
        if not ctx.title_filter(title):
            continue
        location = (post.get("categories") or {}).get("location", "") or ""
        city = ctx.infer_city(location)
        if not city:
            continue
        posted_dt = _parse_epoch_ms(post.get("createdAt"))
        if not ctx.within_recency(posted_dt):
            continue
        found.append(ctx.make_job(
            company=name, title=title, url=post.get("hostedUrl", ""), city=city,
            location=location, source=ctx.source("lever"), posted_dt=posted_dt,
            posted_label=posted_dt.date().isoformat() if posted_dt else "",
        ))
    return found


def scrape_phenom(ctx, name, base):
    """Phenom People JSON API (jobs[].data)."""
    found = []
    page = 1
    while page <= 50:
        r = requests.get(f"{base}/api/jobs?page={page}&limit=100", headers=_HJSON, timeout=25)
        if r.status_code != 200:
            if page == 1:
                print(f"  [{name}] HTTP {r.status_code}")
            break
        data = r.json()
        jobs = data.get("jobs", [])
        if not jobs:
            break
        for job in jobs:
            d = job.get("data", {})
            title = d.get("title", "")
            if not ctx.title_filter(title):
                continue
            parts = [str(d.get(k, "") or "") for k in ("location_name", "city", "state", "country")]
            extra = d.get("additional_locations") or []
            if isinstance(extra, list):
                parts += [str(x) for x in extra]
            loc = " ".join(p for p in parts if p)
            city = ctx.infer_city(loc)
            if not city:
                continue
            posted_dt = _parse_iso(d.get("posted_date") or "")
            if not ctx.within_recency(posted_dt):
                continue
            found.append(ctx.make_job(
                company=name, title=title, url=d.get("apply_url", ""), city=city,
                location=loc, source=ctx.source("phenom"), posted_dt=posted_dt,
                posted_label=posted_dt.date().isoformat() if posted_dt else "",
            ))
        if page * 100 >= data.get("totalCount", 0):
            break
        page += 1
        time.sleep(0.3)
    return found


def _icims_detail_date(href):
    """iCIMS list pages carry no date; the detail page (also needs in_iframe=1)
    has a JSON-LD datePosted. Returns a UTC datetime or None."""
    url = href if "in_iframe=1" in href else href + ("&" if "?" in href else "?") + "in_iframe=1"
    try:
        r = requests.get(url, headers=_H, timeout=20)
        if r.status_code != 200:
            return None
        m = re.search(r'"datePosted"\s*:\s*"([^"]+)"', r.text)
        return _parse_iso(m.group(1)) if m else None
    except Exception:
        return None


def scrape_icims(ctx, name, subdomain):
    """iCIMS HTML portal. Filter by title + city first, then pay for the
    detail-page fetch (for the date) only on the survivors."""
    from bs4 import BeautifulSoup
    base = f"https://{subdomain}.icims.com"
    found = []
    pr, max_pages = 0, None
    while max_pages is None or pr < max_pages:
        url = f"{base}/jobs/search?ss=1&hashed=-1&in_iframe=1&pr={pr}"
        r = requests.get(url, headers=_H, timeout=25)
        if r.status_code != 200:
            if pr == 0:
                print(f"  [{name}] HTTP {r.status_code}")
            break
        soup = BeautifulSoup(r.text, "html.parser")
        if max_pages is None:
            m = re.search(r"Page\s+\d+\s+of\s+(\d+)", soup.get_text())
            max_pages = int(m.group(1)) if m else 1
        rows = [row for row in soup.select("div.row") if row.select_one("a.iCIMS_Anchor")]
        if not rows:
            break
        for row in rows:
            a = row.select_one("div.title a.iCIMS_Anchor") or row.select_one("a.iCIMS_Anchor")
            if not a or not re.search(r"/jobs/\d+/.+/job", a.get("href", "")):
                continue
            h3 = a.find("h3")
            title = (h3.get_text(strip=True) if h3 else a.get_text(strip=True))
            if not ctx.title_filter(title):
                continue
            loc_el = row.select_one("div.header.left span:not(.field-label)")
            location = loc_el.get_text(strip=True) if loc_el else ""
            desc_el = row.select_one("div.description")
            desc = desc_el.get_text(" ", strip=True) if desc_el else ""
            city = ctx.infer_city(f"{location} {desc}")
            if not city:
                continue
            href = a["href"].split("?")[0]
            posted_dt = _icims_detail_date(href)
            if not ctx.within_recency(posted_dt):
                continue
            found.append(ctx.make_job(
                company=name, title=title, url=href, city=city,
                location=location or desc[:80], source=ctx.source("icims"),
                posted_dt=posted_dt,
                posted_label=posted_dt.date().isoformat() if posted_dt else "",
            ))
        pr += 1
        time.sleep(0.3)
    return found


def _sf_detail_date(host, href):
    """SuccessFactors sites that omit the list date (Voith, McCormick) expose it
    on the detail page as <meta itemprop=datePosted>."""
    from bs4 import BeautifulSoup
    url = href if href.startswith("http") else host + href
    try:
        r = requests.get(url, headers=_H, timeout=20)
        if r.status_code != 200:
            return None
        meta = BeautifulSoup(r.text, "html.parser").select_one('meta[itemprop="datePosted"]')
        return _parse_sf_meta(meta.get("content")) if meta else None
    except Exception:
        return None


# SF boards return results newest-first, so once we see an inline date older
# than the recency window every later row is older too — stop paging. Sites
# without an inline date (Voith, McCormick) can't be early-stopped that way, so
# they're bounded by MAX_SF_PAGES (recent jobs are on the first pages anyway).
MAX_SF_PAGES = 6


def scrape_successfactors(ctx, name, host, page_size):
    """SuccessFactors Career Site Builder HTML search. tr.data-row dedupes the
    desktop/mobile title links cleanly (selecting anchors directly double-counts).
    Inline span.jobDate when present, else detail-page meta — fetched only for
    title+city survivors."""
    from bs4 import BeautifulSoup
    found = []
    startrow = total = None
    pages = 0
    while pages < MAX_SF_PAGES:
        r = requests.get(f"{host}/search/?q=&startrow={startrow or 0}", headers=_H, timeout=30)
        if r.status_code != 200:
            if not startrow:
                print(f"  [{name}] HTTP {r.status_code}")
            break
        soup = BeautifulSoup(r.text, "html.parser")
        if total is None:
            label = soup.select_one(".paginationLabel")
            m = re.search(r"of\s*([\d,]+)", label.get_text()) if label else None
            total = int(m.group(1).replace(",", "")) if m else 0
        rows = soup.select("tr.data-row")
        if not rows:
            break
        stop = False
        for row in rows:
            a = row.select_one("a.jobTitle-link")
            if not a:
                continue
            date_el = row.select_one("td.colDate span.jobDate")
            inline_dt = _parse_sf_inline(date_el.get_text(strip=True)) if date_el else None
            # Newest-first: first too-old inline date means we're past the window.
            if inline_dt is not None and not ctx.within_recency(inline_dt):
                stop = True
                break
            title = a.get_text(strip=True)
            if not ctx.title_filter(title):
                continue
            loc_el = row.select_one("td.colLocation span.jobLocation") or row.select_one("span.jobLocation")
            location = loc_el.get_text(strip=True) if loc_el else ""
            city = ctx.infer_city(location)
            if not city:
                continue
            href = a["href"]
            posted_dt = inline_dt if inline_dt is not None else _sf_detail_date(host, href)
            if not ctx.within_recency(posted_dt):
                continue
            found.append(ctx.make_job(
                company=name, title=title, url=host + href, city=city,
                location=location, source=ctx.source("successfactors"),
                posted_dt=posted_dt,
                posted_label=posted_dt.date().isoformat() if posted_dt else "",
            ))
        pages += 1
        startrow = (startrow or 0) + page_size
        if stop or startrow >= total:
            break
        time.sleep(0.4)
    if pages >= MAX_SF_PAGES and total and startrow < total:
        print(f"  [{name}] page cap hit ({MAX_SF_PAGES} pages of {total} jobs) — "
              "undated site, deeper pages not scanned")
    return found


# --- Orchestration ------------------------------------------------------------

def _safe(label, fn, *args):
    """Isolate each company so one platform/network failure doesn't lose the
    rest of the run (mirrors scraper_finance._playwright_companies)."""
    try:
        jobs = fn(*args)
        if jobs:
            print(f"  [{label}] {len(jobs)} match(es)")
        return jobs
    except Exception as exc:
        print(f"  [{label}] error: {exc}")
        return []


def collect_extra_jobs(*, title_filter, infer_city, within_recency, make_job, source_suffix):
    """Scrape every non-Workday/Greenhouse platform and return job dicts in the
    caller's make_job shape.

    The caller supplies its vertical-specific helpers so this module owns only
    platform logic:
      title_filter(title)   -> bool   (entry-finance vs entry-sales gate)
      infer_city(location)  -> str    (maps an ATS location to a metro code)
      within_recency(dt)    -> bool   (2-day window; drops unknown dates)
      make_job(**kwargs)    -> dict   (tags the right vertical)
      source_suffix         -> "finance" | "sales"  (for the source field)
    """
    ctx = SimpleNamespace(
        title_filter=title_filter,
        infer_city=infer_city,
        within_recency=within_recency,
        make_job=make_job,
        source=lambda platform: f"{platform}-{source_suffix}",
    )
    jobs = []
    for name, host, site in ORACLE_COMPANIES:
        print(f"[Oracle] {name}…")
        jobs += _safe(name, scrape_oracle, ctx, name, host, site)
        time.sleep(0.3)
    for name, handle in LEVER_COMPANIES:
        print(f"[Lever] {name}…")
        jobs += _safe(name, scrape_lever, ctx, name, handle)
        time.sleep(0.3)
    for name, base in PHENOM_COMPANIES:
        print(f"[Phenom] {name}…")
        jobs += _safe(name, scrape_phenom, ctx, name, base)
        time.sleep(0.3)
    for name, subdomain in ICIMS_COMPANIES:
        print(f"[iCIMS] {name}…")
        jobs += _safe(name, scrape_icims, ctx, name, subdomain)
        time.sleep(0.3)
    for name, host, page_size in SUCCESSFACTORS_COMPANIES:
        print(f"[SuccessFactors] {name}…")
        jobs += _safe(name, scrape_successfactors, ctx, name, host, page_size)
        time.sleep(0.3)
    return jobs
