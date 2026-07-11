"""Project Management scraper — project-management roles at $1B+ employers,
scoped to South Carolina's major metros. Sibling of the SCM track: it reuses
scraper_scm's shared SC employer union, SC-metro inference, and 7-day recency,
swapping only the title filter (project-management roles) and the vertical tag.

Writes shared_jobs_project.json. Runs in the 9 AM cron chain after scraper_scm.

No salary floor or experience exclusion — the $1B+-employer and SC-location
constraints do the filtering (same reasoning as the SCM / IT / HR tracks).

Metros (slug): charleston-sc, columbia-sc, greenville-sc, rock-hill-sc.
"""
import re
import sys
from pathlib import Path

import scraper_scm
from corporate_filter import is_corporate_role

SHARED_JOBS_FILE = Path(__file__).resolve().parent / "shared_jobs_project.json"

# Workday search terms (the platform search narrows the fetch before the title
# filter runs). Keep broad — the title filter below is the real gate.
PROJECT_SEARCH_TERMS = [
    "project manager", "project management", "project coordinator",
    "pmo", "project lead", "program manager",
]

# Keep in sync with app/matching.py::PROJECT_KEYWORDS.
PROJECT_KEYWORDS = (
    "project manager", "project management", "project coordinator",
    "project lead", "project analyst", "project specialist",
    "project director", "project administrator", "pmo",
    "program manager", "program management",
)
PROJECT_NEGATIVE_KEYWORDS = ("intern", "internship")


def title_is_project(title: str) -> bool:
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not t:
        return False
    if not is_corporate_role(t):
        return False
    if any(neg in t for neg in PROJECT_NEGATIVE_KEYWORDS):
        return False
    return any(kw in t for kw in PROJECT_KEYWORDS)


def main() -> int:
    return scraper_scm.run(
        title_filter=title_is_project,
        vertical="project",
        source_suffix="project",
        search_terms=PROJECT_SEARCH_TERMS,
        out_file=SHARED_JOBS_FILE,
        label="Project Management",
    )


if __name__ == "__main__":
    sys.exit(main())
