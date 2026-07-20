"""Combined operations-tracks scraper: supply chain + project management +
data/business analyst in ONE sweep of the $1B+ employer union.

Replaces the three sequential scraper_scm.py / scraper_project.py /
scraper_analyst.py cron entries (2026-07-20) — each swept the same ~150
boards, tripling the nightly chain's runtime. Workday boards are queried
once per deduped union search term; each posting is routed to every track
whose title filter matches. Writes all three shared_jobs_*.json files.

The standalone scrapers still work for one-off runs.
"""
import sys

import scraper_analyst
import scraper_project
import scraper_scm


def main() -> int:
    return scraper_scm.run_multi([
        {
            "title_filter": scraper_scm.title_is_scm,
            "vertical": "scm",
            "source_suffix": "scm",
            "search_terms": scraper_scm.SCM_SEARCH_TERMS,
            "out_file": scraper_scm.SHARED_JOBS_FILE,
            "label": "SCM",
        },
        {
            "title_filter": scraper_project.title_is_project,
            "vertical": "project",
            "source_suffix": "project",
            "search_terms": scraper_project.PROJECT_SEARCH_TERMS,
            "out_file": scraper_project.SHARED_JOBS_FILE,
            "label": "Project Management",
        },
        {
            "title_filter": scraper_analyst.title_is_analyst,
            "vertical": "analyst",
            "source_suffix": "analyst",
            "search_terms": scraper_analyst.ANALYST_SEARCH_TERMS,
            "out_file": scraper_analyst.SHARED_JOBS_FILE,
            "label": "Analyst",
        },
    ])


if __name__ == "__main__":
    sys.exit(main())
