"""Salary + description enrichment shared by the vertical scrapers.

Before job_enrich, only the PM scraper fetched a posting body, so every
finance / sales / IT / HR / SCM / project / analyst job reached the board with
no pay range even when the posting published one (1,756 of 1,989 rows on
2026-07-25).
"""
import pathlib

import pytest

from app.ingest import _normalize_one
from app.parsing import parse_salary_in_context
from job_enrich import enrich_job, html_to_text, salary_fields, workday_detail


# The real GE Vernova posting that surfaced this bug — the phrasing is prose,
# not a "$X - $Y" range, and the amounts carry cents.
GE_VERNOVA = (
    "Relocation Assistance Provided: Yes For candidates applying to a U.S. based "
    "position, the pay range for this position is between $132,200.00 and $220,400.00. "
    "The Company pays a geographic differential of 110%, 120% or 130% of salary in "
    "certain areas. Bonus eligibility: discretionary annual bonus."
)


def test_prose_pay_range_is_parsed():
    assert parse_salary_in_context(GE_VERNOVA) == (132_200, 220_400)


def test_salary_fields_formats_the_board_label():
    assert salary_fields(GE_VERNOVA) == {
        "salary_label": "$132,200 – $220,400",
        "salary_min": 132_200,
        "salary_max": 220_400,
    }


def test_amounts_with_no_compensation_context_are_not_a_salary():
    """A description is full of numbers that aren't pay. A wrong range on the
    card is worse than an empty one."""
    assert salary_fields("The client invested $250,000 into the programme.") == {
        "salary_label": "", "salary_min": None, "salary_max": None,
    }


def test_a_real_range_beats_an_isolated_amount_earlier_in_the_text():
    """Regression: the first compensation-ish snippet used to win, so a bonus
    figure near the top blocked the actual range further down."""
    text = (
        "Compensation includes a sign-on bonus of $60,000. "
        "The base salary range for this role is $150,000 - $190,000."
    )
    assert parse_salary_in_context(text) == (150_000, 190_000)


def test_html_description_is_flattened_without_welding_words():
    text = html_to_text("<ul><li>Pay range:</li><li>$120,000</li><li>to $140,000</li></ul>")
    assert text == "Pay range: $120,000 to $140,000"
    assert salary_fields(text)["salary_min"] == 120_000


def test_script_and_style_blocks_are_dropped():
    assert html_to_text("<style>.a{color:red}</style><p>Base pay $99,000</p>") == "Base pay $99,000"


def test_enrich_job_fills_description_salary_and_experience():
    job = {"title": "Senior Project Manager", "description": "", "salary_label": "",
           "salary_min": None, "salary_max": None,
           "experience_min": None, "experience_max": None}
    enrich_job(job, GE_VERNOVA + " Requires a minimum of 8 years of experience.")

    assert job["salary_label"] == "$132,200 – $220,400"
    assert job["salary_min"] == 132_200
    assert job["description"].startswith("Relocation Assistance")
    assert job["experience_min"] == 8


def test_enrich_job_does_not_overwrite_a_platform_supplied_salary():
    """A real salary field from the ATS beats anything parsed out of prose."""
    job = {"title": "Analyst", "description": "already here", "salary_label": "$100,000",
           "salary_min": 100_000, "salary_max": 100_000,
           "experience_min": None, "experience_max": None}
    enrich_job(job, GE_VERNOVA)

    assert job["salary_label"] == "$100,000"
    assert job["salary_min"] == 100_000
    assert job["description"] == "already here"


def test_enrich_job_survives_an_empty_description():
    job = {"title": "Analyst", "description": "", "salary_label": "",
           "salary_min": None, "salary_max": None,
           "experience_min": None, "experience_max": None}
    enrich_job(job, "")
    assert job["salary_label"] == ""
    assert job["salary_min"] is None


def test_workday_detail_returns_description_and_locations(monkeypatch):
    calls = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"jobPostingInfo": {
                "jobDescription": f"<p>{GE_VERNOVA}</p>",
                "location": "Atlanta, GA",
                "additionalLocations": ["Houston, TX"],
            }}

    def _get(url, **kwargs):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr("job_enrich.requests.get", _get)
    detail = workday_detail("gevernova", 5, "Vernova_ExternalSite", "/job/Atlanta/Cached-Role_R1")
    assert detail["locations"] == ["Atlanta, GA", "Houston, TX"]
    assert salary_fields(detail["description"])["salary_min"] == 132_200

    # Cached: the same posting comes back under several search terms, and each
    # re-fetch is a wasted request against the employer's ATS.
    workday_detail("gevernova", 5, "Vernova_ExternalSite", "/job/Atlanta/Cached-Role_R1")
    assert len(calls) == 1


def test_workday_detail_swallows_a_failed_fetch(monkeypatch):
    def _boom(url, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("job_enrich.requests.get", _boom)
    assert workday_detail("t", 5, "site", "/job/Nowhere/Broken_R9") == {
        "description": "", "locations": [],
    }


def test_ingest_derives_salary_from_a_feed_description():
    """Backstop for a platform whose scraper isn't wired up yet — and it means
    re-syncing an old feed picks up the range the board was missing."""
    job = _normalize_one(
        {"title": "Program Manager", "description": GE_VERNOVA,
         "salary_label": "", "salary_min": None, "salary_max": None},
        "scm",
    )
    assert job["salary_label"] == "$132,200 – $220,400"
    assert job["salary_min"] == 132_200


def test_ingest_hides_a_sub_floor_salary_on_a_pm_posting():
    """The PM track gates on $180K, so publishing a newly-parsed low salary
    would delete the job from the board instead of informing anyone — that is
    the rule scraper.py has always applied at scrape time."""
    job = _normalize_one(
        {"title": "Program Manager", "salary_label": "", "salary_min": None,
         "salary_max": None,
         "description": "The base pay range for this role is $90,000 - $110,000."},
        "pm",
    )
    assert job["salary_label"] == ""
    assert job["salary_min"] is None
    # The description is still stored — only the salary is withheld.
    assert "base pay range" in job["description"]


def test_ingest_publishes_a_sub_floor_salary_on_other_tracks():
    """No other vertical has a pay floor, so an $80K HR job shows its $80K."""
    job = _normalize_one(
        {"title": "HR Generalist", "salary_label": "", "salary_min": None,
         "salary_max": None,
         "description": "The base pay range for this role is $70,000 - $80,000."},
        "hr",
    )
    assert job["salary_label"] == "$70,000 – $80,000"


def test_ingest_leaves_an_existing_salary_alone():
    job = _normalize_one(
        {"title": "Program Manager", "description": GE_VERNOVA,
         "salary_label": "$90,000", "salary_min": 90_000, "salary_max": 90_000},
        "scm",
    )
    assert job["salary_label"] == "$90,000"


@pytest.mark.parametrize("scraper", [
    "scraper_finance.py", "scraper_sales.py", "scraper_it.py",
    "scraper_hr.py", "scraper_scm.py", "scraper_ats_extra.py",
])
def test_every_vertical_scraper_enriches(scraper):
    """Regression guard: a vertical that stops enriching silently ships jobs
    with no pay range, which is exactly the bug this module was written for."""
    source = (pathlib.Path(__file__).resolve().parent.parent / scraper).read_text()
    assert "from job_enrich import" in source, f"{scraper} must import the shared enrichment"
    assert "enrich_job(" in source, f"{scraper} must call enrich_job on its scraped jobs"
