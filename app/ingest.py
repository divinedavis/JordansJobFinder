from urllib.parse import urlparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from posted_dates import parse_relative_posted

from .matching import PM_MIN_SALARY, job_excluded, normalize_text
from .parsing import (
    format_salary_label,
    parse_experience_years,
    parse_salary,
    parse_salary_in_context,
)




def _safe_url(url):
    try:
        p = urlparse(url)
        if p.scheme in ("http", "https"):
            return url
    except Exception:
        pass
    return ""

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_STORE = REPO_ROOT / "jobs_store.json"
SHARED_JOBS_FILE = REPO_ROOT / "shared_jobs.json"
SHARED_JOBS_FINANCE_FILE = REPO_ROOT / "shared_jobs_finance.json"
SHARED_JOBS_SALES_FILE = REPO_ROOT / "shared_jobs_sales.json"
SHARED_JOBS_IT_FILE = REPO_ROOT / "shared_jobs_it.json"
SHARED_JOBS_HR_FILE = REPO_ROOT / "shared_jobs_hr.json"
SHARED_JOBS_SCM_FILE = REPO_ROOT / "shared_jobs_scm.json"
SHARED_JOBS_PROJECT_FILE = REPO_ROOT / "shared_jobs_project.json"
SHARED_JOBS_ANALYST_FILE = REPO_ROOT / "shared_jobs_analyst.json"


def parse_posted_datetime(raw_value: Optional[str]):
    if not raw_value:
        return None
    value = raw_value.strip()
    if not value or value == "Unknown":
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Workday's relative dialect ("Posted 30+ Days Ago") plus ISO 8601 with a
    # time/offset. The relative case matters here as well as in the scraper:
    # this is the self-heal path for feed rows that arrived with no posted_at,
    # and without it a stale posting is stored with posted_at NULL, which makes
    # every recency filter fall back to found_at and treat it as brand new.
    return parse_relative_posted(value)


def load_legacy_jobs() -> list[dict]:
    if not LEGACY_STORE.exists():
        return []
    return json.loads(LEGACY_STORE.read_text())


def load_shared_jobs() -> list[dict]:
    if not SHARED_JOBS_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_FILE.read_text())


def load_finance_jobs() -> list[dict]:
    if not SHARED_JOBS_FINANCE_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_FINANCE_FILE.read_text())


def load_sales_jobs() -> list[dict]:
    if not SHARED_JOBS_SALES_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_SALES_FILE.read_text())


def load_it_jobs() -> list[dict]:
    if not SHARED_JOBS_IT_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_IT_FILE.read_text())


def load_hr_jobs() -> list[dict]:
    if not SHARED_JOBS_HR_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_HR_FILE.read_text())


def load_scm_jobs() -> list[dict]:
    if not SHARED_JOBS_SCM_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_SCM_FILE.read_text())


def load_project_jobs() -> list[dict]:
    if not SHARED_JOBS_PROJECT_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_PROJECT_FILE.read_text())


def load_analyst_jobs() -> list[dict]:
    if not SHARED_JOBS_ANALYST_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_ANALYST_FILE.read_text())


def normalize_legacy_job(job: dict) -> dict:
    title = job.get("title", "")
    posted_label = job.get("posted") or "Unknown"
    description = job.get("description", "")
    parsed_experience = parse_experience_years(title, description)
    salary_label = job.get("salary") or ""
    salary_bounds = parse_salary(salary_label) or parse_salary(description or "")
    if salary_bounds and (not salary_label or salary_label == "See posting"):
        salary_label = format_salary_label(salary_bounds)
    found_at = job.get("found_at")
    found_dt = None
    if found_at:
        try:
            found_dt = datetime.fromisoformat(found_at.replace("Z", "+00:00"))
        except ValueError:
            found_dt = None

    return {
        "source": "legacy-shared-crawl",
        "company": job.get("company", ""),
        "title": title,
        "normalized_title": normalize_text(title),
        "url": _safe_url(job.get("url", "")),
        "city": job.get("city", ""),
        "location": job.get("location", ""),
        "description": description,
        "salary_label": salary_label,
        "salary_min": salary_bounds[0] if salary_bounds else None,
        "salary_max": salary_bounds[1] if salary_bounds else None,
        "posted_label": posted_label,
        "posted_at": parse_posted_datetime(posted_label),
        "experience_min": parsed_experience.min_years,
        "experience_max": parsed_experience.max_years,
        "is_technical": True,
        "found_at": found_dt,
    }


def normalized_legacy_jobs() -> list[dict]:
    return [
        normalize_legacy_job(job)
        for job in load_legacy_jobs()
        if not job_excluded(job.get("company", ""), job.get("city", ""))
    ]


def _normalize_one(job: dict, default_vertical: str) -> dict:
    parsed = dict(job)
    for key in ("posted_at", "found_at"):
        value = parsed.get(key)
        if isinstance(value, str) and value:
            try:
                parsed[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                parsed[key] = None
    # Self-heal: if the feed gave us a posted_label but no usable posted_at,
    # derive it from the label. Otherwise the recency filter falls back to
    # found_at (which is bumped every scrape) and a stale job looks fresh.
    if not parsed.get("posted_at"):
        parsed["posted_at"] = parse_posted_datetime(parsed.get("posted_label"))
    # Self-heal: a feed that carries a description but no salary gets one
    # parsed here. The scrapers do this at scrape time (job_enrich); this is
    # the backstop for a platform that isn't wired up yet, and it means a
    # re-sync of an old feed picks up the pay range the board was missing.
    if parsed.get("salary_min") is None and not parsed.get("salary_label"):
        bounds = parse_salary_in_context(parsed.get("description") or "")
        # A sub-floor salary on a PM posting is dropped, not published — the
        # same rule scraper.py has always applied. Publishing it here would
        # make the job fail the PM track's salary gate and vanish from the
        # board, which is a deletion dressed up as a display fix.
        if bounds and parsed.get("vertical", default_vertical) == "pm" and bounds[1] < PM_MIN_SALARY:
            bounds = None
        if bounds:
            parsed["salary_label"] = format_salary_label(bounds)
            parsed["salary_min"], parsed["salary_max"] = bounds
    parsed.setdefault("vertical", default_vertical)
    return parsed


def normalized_shared_jobs() -> list[dict]:
    pm_jobs = [_normalize_one(j, "pm") for j in load_shared_jobs()]
    finance_jobs = [_normalize_one(j, "finance") for j in load_finance_jobs()]
    sales_jobs = [_normalize_one(j, "sales") for j in load_sales_jobs()]
    it_jobs = [_normalize_one(j, "it") for j in load_it_jobs()]
    hr_jobs = [_normalize_one(j, "hr") for j in load_hr_jobs()]
    scm_jobs = [_normalize_one(j, "scm") for j in load_scm_jobs()]
    project_jobs = [_normalize_one(j, "project") for j in load_project_jobs()]
    analyst_jobs = [_normalize_one(j, "analyst") for j in load_analyst_jobs()]
    scraped = (pm_jobs + finance_jobs + sales_jobs + it_jobs + hr_jobs
               + scm_jobs + project_jobs + analyst_jobs)
    scraped_any = bool(scraped)
    combined = [
        job
        for job in scraped
        if not job_excluded(job.get("company", ""), job.get("city", ""))
    ]
    # Fall back to the legacy static file only when the feeds produced NOTHING
    # to begin with. "Every posting was filtered out" is a real result and must
    # not silently resurrect stale legacy data — a plausible outcome now that
    # the $1B revenue bar can empty a small feed.
    if combined or scraped_any:
        return combined
    return normalized_legacy_jobs()
