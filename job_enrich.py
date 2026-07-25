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
    """Fetch one Workday posting: {"description": str, "locations": [str]}.

    The CXS detail endpoint is the same one the "N Locations" fix already used,
    so a caller that needs both pays for a single request. Every failure is
    swallowed — a posting with no description is still a posting.
    """
    if not ext_path:
        return {"description": "", "locations": []}
    api = f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{ext_path}"
    if api in _WORKDAY_DETAIL_CACHE:
        return _WORKDAY_DETAIL_CACHE[api]

    detail = {"description": "", "locations": []}
    try:
        resp = requests.get(api, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            info = resp.json().get("jobPostingInfo") or {}
            detail["description"] = html_to_text(info.get("jobDescription") or "")
            locations = [info.get("location") or ""]
            locations.extend(info.get("additionalLocations") or [])
            detail["locations"] = [loc for loc in locations if loc]
    except Exception:
        pass

    _WORKDAY_DETAIL_CACHE[api] = detail
    return detail


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
