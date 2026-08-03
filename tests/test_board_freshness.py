"""Guards for the two things a board card promises: a real salary, and a link
to a job that still exists.

Both were broken on 2026-08-03 and both came from the same place — the PM
scraper read Workday's *posting page* instead of its CXS endpoint:

- myworkdayjobs.com serves a JavaScript shell to a plain GET, so the stored
  description was "Workday is currently unavailable. English العربية …" and no
  salary was ever found. Every Workday PM job showed "See posting" (rendered as
  nothing) while CrowdStrike's posting published $140,000 - $215,000.
- Relative labels ("Posted Today") were stored raw and re-resolved against the
  clock on every run, so a posting first seen in March was posted *today*,
  forever: it could never age out and its link had long since died.
"""
from datetime import datetime, timedelta, timezone

import pytest

import scraper
from app.parsing import parse_salary_in_context
from job_enrich import workday_api_url

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _ago(days):
    """A real past instant — purge_old_store reads the wall clock."""
    return datetime.now(timezone.utc) - timedelta(days=days)


# ── Salary ───────────────────────────────────────────────────────────────────

# Warner Bros' real posting. The range is preceded by a paragraph of
# compensation prose, which is what broke it.
WARNER_BROS = (
    "Compensation: Pay is based on a number of factors including but not limited to "
    "external market data, internal equity, location, skill set, experience, and/or "
    "performance. Base pay is just one component of Warner Bros. Discovery's total "
    "compensation package for employees. Pay Range: $301,350.00 - $559,650.00 salary "
    "per year. Other rewards may include annual bonuses and long-term incentives."
)

CROWDSTRIKE = (
    "The base salary range for this position for all U.S. candidates is "
    "$140,000 - $215,000 per year, with eligibility for bonuses, equity grants and a "
    "comprehensive benefits package."
)


def test_range_survives_a_paragraph_of_compensation_prose():
    """The context windows used to be carved out non-overlapping, so the window
    opened at "Base pay" ended between the two amounts and the "Pay" that would
    have covered the whole range had already been consumed. $559,650 was lost
    and the card would have read a flat $301,350."""
    assert parse_salary_in_context(WARNER_BROS) == (301_350, 559_650)


def test_range_whose_floor_is_under_the_pm_minimum_still_reads_as_a_range():
    assert parse_salary_in_context(CROWDSTRIKE) == (140_000, 215_000)


def test_workday_detail_reads_the_cxs_endpoint_not_the_posting_page(monkeypatch):
    """A plain GET of the posting page returns a JS shell. If this ever goes
    back to scraping HTML, every Workday PM job loses its salary again."""
    calls = []

    def fake_detail(url, timeout=15):
        calls.append(url)
        return {"description": CROWDSTRIKE, "locations": [], "posted": "Posted 3 Days Ago",
                "status": 200}

    monkeypatch.setattr(scraper, "workday_detail_by_url", fake_detail)
    url = ("https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/job/"
           "USA---New-York-NY/Sr-Product-Manager_R29578")
    salary, description, posted = scraper.fetch_workday_detail(url)
    assert calls == [url]
    assert salary == "$140,000 – $215,000"
    assert description == CROWDSTRIKE
    assert posted == "Posted 3 Days Ago"


@pytest.mark.parametrize("url,expected", [
    ("https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/job/NY/Sr-PM_R1",
     "https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/crowdstrikecareers/job/NY/Sr-PM_R1"),
    # Some tenants link without the locale segment.
    ("https://warnerbros.wd5.myworkdayjobs.com/global/job/NY/VP_R2",
     "https://warnerbros.wd5.myworkdayjobs.com/wday/cxs/warnerbros/global/job/NY/VP_R2"),
    ("https://boards.greenhouse.io/robinhood/jobs/7968044", ""),
])
def test_workday_api_url(url, expected):
    assert workday_api_url(url) == expected


# ── Freshness ────────────────────────────────────────────────────────────────

def test_relative_label_is_frozen_against_when_it_was_read():
    assert scraper.freeze_posted_label("Posted Today", NOW) == "2026-08-03"
    assert scraper.freeze_posted_label("Posted 3 Days Ago", NOW) == "2026-07-31"


def test_absolute_and_unparseable_labels_are_left_alone():
    assert scraper.freeze_posted_label("2026-07-30", NOW) == "2026-07-30"
    assert scraper.freeze_posted_label("July 30, 2026", NOW) == "July 30, 2026"
    assert scraper.freeze_posted_label("Unknown", NOW) == "Unknown"
    assert scraper.freeze_posted_label("", NOW) == ""


def test_a_stored_posted_today_ages_out_instead_of_living_forever():
    """The bug in one test: a March posting labelled "Posted Today" was still on
    the NYC board in August because the label was re-read against the clock
    every run."""
    discovered = _ago(133)
    store = [{
        "url": "https://ms.wd5.myworkdayjobs.com/en-US/External/job/NY/Senior-PM_JR1",
        "title": "Senior Product Manager", "posted": "Posted Today",
        "found_at": discovered.isoformat(),
    }]
    assert scraper.purge_old_store(store) == [store[0]], "unfrozen, it never ages out"

    frozen = scraper.freeze_store_posted_labels(store)
    assert frozen[0]["posted"] == discovered.strftime("%Y-%m-%d")
    assert scraper.purge_old_store(frozen) == []


def test_freezing_keeps_a_posting_that_really_is_recent():
    store = [{"url": "https://ex.wd5.myworkdayjobs.com/en-US/S/job/NY/PM_R1",
              "title": "PM", "posted": "Posted Today", "found_at": _ago(0).isoformat()}]
    assert len(scraper.purge_old_store(scraper.freeze_store_posted_labels(store))) == 1


# ── Removed postings ─────────────────────────────────────────────────────────

def test_only_a_404_drops_a_posting(monkeypatch):
    """A WAF 403 (Morgan Stanley blocks the droplet's whole range) or a timeout
    must never be read as "the employer pulled this req"."""
    import job_enrich

    statuses = {"gone": 404, "blocked": 403, "flaky": 0, "live": 200}

    def fake_detail(api, timeout=15):
        key = api.rsplit("_", 1)[-1]
        return {"description": "", "locations": [], "posted": "", "status": statuses[key]}

    monkeypatch.setattr(job_enrich, "workday_detail_by_api_url", fake_detail)

    store = [{"url": f"https://ex.wd5.myworkdayjobs.com/en-US/S/job/NY/PM_{key}",
              "title": "PM", "company": "Ex"} for key in statuses]
    kept = {job["url"].rsplit("_", 1)[-1] for job in scraper.drop_removed_postings(store)}
    assert kept == {"blocked", "flaky", "live"}


def test_a_non_workday_posting_is_never_probed(monkeypatch):
    """No URL to build a CXS request from means no request at all — a
    Greenhouse card can't be deleted by a Workday sweep."""
    import job_enrich

    monkeypatch.setattr(job_enrich, "workday_detail_by_api_url",
                        lambda api, timeout=15: pytest.fail("probed a non-Workday URL"))
    store = [{"url": "https://boards.greenhouse.io/robinhood/jobs/1", "title": "PM"}]
    assert scraper.drop_removed_postings(store) == store
