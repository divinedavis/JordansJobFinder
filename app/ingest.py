import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .matching import normalize_text, parse_experience_years


REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_STORE = REPO_ROOT / "jobs_store.json"
SHARED_JOBS_FILE = REPO_ROOT / "shared_jobs.json"


def parse_posted_datetime(raw_value: Optional[str]):
    if not raw_value:
        return None
    value = raw_value.strip()
    if not value:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def load_legacy_jobs() -> list[dict]:
    if not LEGACY_STORE.exists():
        return []
    return json.loads(LEGACY_STORE.read_text())


def load_shared_jobs() -> list[dict]:
    if not SHARED_JOBS_FILE.exists():
        return []
    return json.loads(SHARED_JOBS_FILE.read_text())


def normalize_legacy_job(job: dict) -> dict:
    title = job.get("title", "")
    posted_label = job.get("posted") or "Unknown"
    parsed_experience = parse_experience_years(title, job.get("description", ""))
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
        "url": job.get("url", ""),
        "city": job.get("city", ""),
        "location": job.get("location", ""),
        "description": job.get("description"),
        "salary_label": job.get("salary"),
        "posted_label": posted_label,
        "posted_at": parse_posted_datetime(posted_label),
        "experience_min": parsed_experience.min_years,
        "experience_max": parsed_experience.max_years,
        "is_technical": True,
        "found_at": found_dt,
    }


def normalized_legacy_jobs() -> list[dict]:
    return [normalize_legacy_job(job) for job in load_legacy_jobs()]


def normalized_shared_jobs() -> list[dict]:
    shared_jobs = load_shared_jobs()
    if shared_jobs:
        normalized = []
        for job in shared_jobs:
            parsed = dict(job)
            for key in ("posted_at", "found_at"):
                value = parsed.get(key)
                if isinstance(value, str) and value:
                    try:
                        parsed[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        parsed[key] = None
            normalized.append(parsed)
        return normalized
    return normalized_legacy_jobs()
