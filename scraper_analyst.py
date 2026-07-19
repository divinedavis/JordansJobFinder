"""Data / Business Analyst scraper — analytics IC roles at $1B+ employers
across the nationwide metro set.

Writes to shared_jobs_analyst.json. Thin wrapper over scraper_scm.run():
same employer union (IT/sales/finance verified set + SC registry + the
2026-07-19 top-10-city wave), same nationwide CITY_LOCATION_PATTERNS, same
7-day recency — only the title filter, search terms, and vertical differ.

Finance-track vocabulary (financial/credit/investment analyst, audit, tax,
actuarial, treasury) is deliberately excluded so postings don't flip between
the finance and analyst verticals on successive syncs (DB upsert is by URL).
Keep ANALYST_KEYWORDS in sync with app/matching.py::ANALYST_KEYWORDS.
"""
import re
import sys
from pathlib import Path

from corporate_filter import is_corporate_role
from scraper_scm import run

SHARED_JOBS_FILE = Path(__file__).resolve().parent / "shared_jobs_analyst.json"

ANALYST_SEARCH_TERMS = [
    "data analyst",
    "business analyst",
    "business intelligence",
    "product analyst",
    "reporting analyst",
    "analytics",
]

ANALYST_KEYWORDS = (
    "data analyst", "business analyst", "business intelligence",
    "bi analyst", "bi developer", "analytics analyst", "product analyst",
    "product operations", "business systems analyst", "reporting analyst",
    "insights analyst", "data quality analyst", "marketing analyst",
    "operations analyst", "strategy analyst",
)
ANALYST_NEGATIVE_KEYWORDS = (
    "financial analyst", "finance analyst", "credit analyst",
    "investment analyst", "audit", "tax", "actuarial", "treasury",
    "director", "vice president", " vp", "vp ", "head of", "chief",
    "intern", "internship",
)


def title_is_analyst(title: str) -> bool:
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not t:
        return False
    if not is_corporate_role(t):
        return False
    if any(neg in t for neg in ANALYST_NEGATIVE_KEYWORDS):
        return False
    return any(kw in t for kw in ANALYST_KEYWORDS)


def main() -> int:
    return run(
        title_filter=title_is_analyst,
        vertical="analyst",
        source_suffix="analyst",
        search_terms=ANALYST_SEARCH_TERMS,
        out_file=SHARED_JOBS_FILE,
        label="Analyst",
    )


if __name__ == "__main__":
    sys.exit(main())
