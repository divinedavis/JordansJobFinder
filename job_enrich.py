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

    _WORKDAY_DETAIL_CACHE[api] = detail
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
