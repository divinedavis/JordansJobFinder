"""Description + salary enrichment shared by every vertical scraper.

Only scraper.py (the PM track) ever fetched a posting's description, so every
job from the finance / sales / IT / HR / SCM / project / analyst tracks reached
the board with no pay range — even when the posting published one in plain
sight. On 2026-07-25 that was 1,756 of 1,989 rows.

The two rules this module exists to keep:

- **Enrich AFTER the cheap filters.** Title, city and recency are decided from
  the list payload; only survivors are worth a detail request. Enriching before
  the filters would multiply the scrape by the size of the whole board.
- **Salary comes from `parse_salary_in_context`, never bare amounts.** A job
  description is full of numbers that are not pay, and a wrong range on the
  card is worse than an empty one.

Workday detail responses are cached per run because the same posting comes back
under several search terms.
"""
import html as html_lib
import re
import time

import requests

from app.parsing import format_salary_label, parse_experience_years, parse_salary_in_context


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

# Descriptions are stored so the board, the tailored-resume prompt and any
# later re-parse can use them. Capped because a handful of ATS pages inline
# their whole benefits handbook.
DESCRIPTION_MAX_CHARS = 20_000

_WORKDAY_DETAIL_CACHE: dict[str, dict] = {}
# A detail fetch that fails for a reason other than "the req is gone" is
# retried once after this pause. Blackstone's NYC PM posting (which publishes
# $165,000 - $185,000) was enriched in 0 seconds on 2026-09-05 — a fast
# non-200 — and reached the board as "See posting" with no description, and
# the next day's scrape skipped it as a duplicate, so one bad request became
# a permanent gap.
WORKDAY_TRANSIENT_RETRY_DELAY = 2.0
_WORKDAY_DEFINITIVE_STATUSES = {200, 404}

# A public Workday posting URL, e.g.
# https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/job/USA---New-York-NY/Sr-PM_R29578
# The locale segment is optional — some tenants link without it.
WORKDAY_URL = re.compile(
    r"^https://(?P<tenant>[^.]+)\.wd(?P<ver>\d+)\.myworkdayjobs\.com/"
    r"(?:[a-zA-Z]{2}-[a-zA-Z]{2}/)?(?P<site>[^/]+)(?P<path>/job/.+)$"
)


def workday_api_url(url: str) -> str:
    """The CXS detail endpoint behind a public Workday posting URL, or "".

    myworkdayjobs.com serves a JavaScript shell to a plain GET — scraping the
    posting page yields "Workday is currently unavailable." and no salary. The
    CXS endpoint is the only readable source for a posting's body, its real
    postedOn, and whether it still exists at all.
    """
    match = WORKDAY_URL.match(url or "")
    if not match:
        return ""
    return (f"https://{match['tenant']}.wd{match['ver']}.myworkdayjobs.com/wday/cxs/"
            f"{match['tenant']}/{match['site']}{match['path']}")


def html_to_text(raw: str) -> str:
    """Flatten ATS description HTML to plain text.

    Tags become spaces rather than being dropped: `<li>$132,200</li><li>and up`
    must not weld into one token, and the salary matcher works on a window of
    characters around a keyword.
    """
    if not raw:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def workday_detail(tenant: str, wd_ver: str | int, site: str, ext_path: str, timeout: int = 15) -> dict:
    """Fetch one Workday posting.

    Returns {"description", "locations", "posted", "status"}. `posted` is the
    posting's own date — Workday's relative `postedOn` ("Posted 3 Days Ago"),
    falling back to the absolute `startDate` — and `status` is the HTTP code, so
    a caller can tell "the employer pulled this req" (404) apart from "the
    request failed" (0, or a WAF's 403). Everything else is swallowed: a posting
    with no description is still a posting.

    The CXS detail endpoint is the same one the "N Locations" fix already used,
    so a caller that needs both pays for a single request.
    """
    if not ext_path:
        return {"description": "", "locations": [], "posted": "", "status": 0}
    api = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{ext_path}"
    return workday_detail_by_api_url(api, timeout=timeout)


def workday_detail_by_api_url(api: str, timeout: int = 15) -> dict:
    if not api:
        return {"description": "", "locations": [], "posted": "", "status": 0}
    if api in _WORKDAY_DETAIL_CACHE:
        return _WORKDAY_DETAIL_CACHE[api]

    detail = _workday_detail_once(api, timeout)
    if detail["status"] not in _WORKDAY_DEFINITIVE_STATUSES:
        # Timeout, 429, 5xx, a WAF hiccup: try once more before giving up.
        time.sleep(WORKDAY_TRANSIENT_RETRY_DELAY)
        detail = _workday_detail_once(api, timeout)

    # Only a definitive answer is worth remembering. Caching a failure meant
    # every later lookup of the same posting in the run — and the vertical
    # scrapers share this cache — inherited the empty body.
    if detail["status"] in _WORKDAY_DEFINITIVE_STATUSES:
        _WORKDAY_DETAIL_CACHE[api] = detail
    return detail


def _workday_detail_once(api: str, timeout: int) -> dict:
    detail = {"description": "", "locations": [], "posted": "", "status": 0}
    try:
        resp = requests.get(api, headers=HEADERS, timeout=timeout)
        detail["status"] = resp.status_code
        if resp.status_code == 200:
            info = resp.json().get("jobPostingInfo") or {}
            detail["description"] = html_to_text(info.get("jobDescription") or "")
            locations = [info.get("location") or ""]
            locations.extend(info.get("additionalLocations") or [])
            detail["locations"] = [loc for loc in locations if loc]
            detail["posted"] = (info.get("postedOn") or info.get("startDate") or "").strip()
    except Exception:
        pass
    return detail


def workday_detail_by_url(url: str, timeout: int = 15) -> dict:
    """Same, addressed by the public posting URL the board links to."""
    return workday_detail_by_api_url(workday_api_url(url), timeout=timeout)


def workday_posting_removed(url: str, timeout: int = 15) -> bool:
    """True only when Workday says the req is gone.

    Deliberately narrow: a timeout, a WAF 403 (Morgan Stanley blocks the
    droplet's whole IP range) or a 5xx must never be read as "removed", or a
    board would delete live jobs on a bad network day.
    """
    api = workday_api_url(url)
    if not api:
        return False
    return workday_detail_by_api_url(api, timeout=timeout)["status"] == 404


def salary_fields(*texts: str) -> dict:
    """{"salary_label", "salary_min", "salary_max"} for the first text that
    yields a pay range. Empty label + None bounds when nothing is found, which
    is what the board reads as "no salary published"."""
    for text in texts:
        bounds = parse_salary_in_context(text or "")
        if bounds:
            return {
                "salary_label": format_salary_label(bounds),
                "salary_min": bounds[0],
                "salary_max": bounds[1],
            }
    return {"salary_label": "", "salary_min": None, "salary_max": None}


def enrich_job(job: dict, *texts: str) -> dict:
    """Fill a scraped job's description, salary and experience from the
    posting text, in place. Existing non-empty values are left alone so a
    platform that publishes a real salary field beats anything parsed here.
    """
    description = next((text for text in texts if text), "")
    if description and not job.get("description"):
        job["description"] = description[:DESCRIPTION_MAX_CHARS]

    if job.get("salary_min") is None and not job.get("salary_label"):
        job.update(salary_fields(*texts))

    if job.get("experience_min") is None and job.get("experience_max") is None and description:
        parsed = parse_experience_years(job.get("title", ""), description)
        job["experience_min"] = parsed.min_years
        job["experience_max"] = parsed.max_years

    return job


# ── Oracle Cloud Recruiting (ORC) ─────────────────────────────────────────────
#
# Uber moved off Workday to Oracle's Candidate Experience app, which is why the
# `uber` Workday tenant returned 0 candidates every morning (422 on every
# version/site pair — per Workday's convention 422 means the tenant does not
# exist, where a real tenant with a wrong site name answers 404).
#
# A public ORC posting URL looks like
# https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/UberCareers/job/301148
# but the REST API is addressed by `siteNumber` (CX_1), not by the site name in
# the path, so the caller has to supply it. Getting it wrong is silent: Oracle
# serves the pod's DEFAULT board for an unknown siteNumber rather than erroring.
ORACLE_URL = re.compile(
    r"^https://(?P<host>[^/]+\.oraclecloud\.com)/hcmUI/CandidateExperience/"
    r"(?P<lang>[^/]+)/sites/(?P<site>[^/]+)/job/(?P<id>\d+)"
)

_ORACLE_DETAIL_CACHE: dict[str, dict] = {}


def oracle_job_url(host: str, site: str, req_id: str) -> str:
    return (f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}"
            f"/job/{req_id}")


def oracle_detail(host: str, site_number: str, req_id: str, timeout: int = 20) -> dict:
    """Fetch one Oracle Cloud Recruiting posting.

    Returns {"description", "locations", "posted", "status"} — the same shape as
    `workday_detail`, so both feed the enrichment path unchanged. The body is
    split across three HTML fields (the corporate boilerplate, the role itself
    and the qualifications); they are concatenated because the pay range lives
    in whichever one the recruiter pasted it into.
    """
    detail = {"description": "", "locations": [], "posted": "", "status": 0}
    if not (host and site_number and req_id):
        return detail

    api = (f"https://{host}/hcmRestApi/resources/latest/"
           f"recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
           f"&finder=ById;Id=%22{req_id}%22,siteNumber={site_number}")
    if api in _ORACLE_DETAIL_CACHE:
        return _ORACLE_DETAIL_CACHE[api]

    try:
        resp = requests.get(api, headers={**HEADERS, "Accept": "application/json"},
                            timeout=timeout)
        detail["status"] = resp.status_code
        if resp.status_code == 200:
            items = (resp.json() or {}).get("items") or []
            info = items[0] if items else {}
            body = " ".join(filter(None, (
                info.get("ExternalDescriptionStr"),
                info.get("ExternalResponsibilitiesStr"),
                info.get("ExternalQualificationsStr"),
                info.get("CorporateDescriptionStr"),
            )))
            detail["description"] = html_to_text(body)[:DESCRIPTION_MAX_CHARS]
            locations = [info.get("PrimaryLocation") or ""]
            locations += [(loc or {}).get("Name") or ""
                          for loc in info.get("secondaryLocations") or []]
            detail["locations"] = [loc for loc in locations if loc]
            # PostedDate is null on the detail resource even when the search
            # result carried one; ExternalPostedStartDate is the field that is
            # actually populated.
            detail["posted"] = ((info.get("ExternalPostedStartDate")
                                 or info.get("PostedDate") or "")[:10]).strip()
    except Exception:
        pass

    _ORACLE_DETAIL_CACHE[api] = detail
    return detail


def oracle_detail_by_url(url: str, site_number: str, timeout: int = 20) -> dict:
    match = ORACLE_URL.match(url or "")
    if not match:
        return {"description": "", "locations": [], "posted": "", "status": 0}
    return oracle_detail(match["host"], site_number, match["id"], timeout=timeout)
