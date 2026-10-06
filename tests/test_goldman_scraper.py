"""Goldman Sachs scraper: higher.gs.com GraphQL items -> board jobs."""
from datetime import datetime, timedelta, timezone

from scraper import goldman_role_to_job

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%dT10:00:00.000Z")


def _item(title, corp="Vice President", city="New York", role_id="184943", status="POSTED",
          posted=TODAY):
    return {"roleId": role_id, "corporateTitle": corp, "jobTitle": title, "status": status,
            "lastPostedDate": posted,
            "locations": [{"city": city, "state": "NY"}],
            "externalSource": {"sourceId": role_id.split("_")[0]}}


def test_city_inside_title_keeps_the_role():
    # The old scraper cut titles at the first "New York" and dropped this one.
    job = goldman_role_to_job(_item(
        "The Core Engineering-New York-Vice President-AI Product Manager - Enterprise Platforms"))
    assert job is not None
    assert job["url"] == "https://higher.gs.com/roles/184943"
    assert job["city"] == "nyc"


def test_lca_notice_is_not_a_real_opening():
    item = _item("Asset & Wealth Management-New York-Vice President, Product Management-4993008",
                 role_id="185037_GS_NOTICE_OF_FILING_LCA")
    assert goldman_role_to_job(item) is None


def test_non_nyc_and_non_target_roles_are_skipped():
    assert goldman_role_to_job(_item("Vice President, Product Management", city="Salt Lake City")) is None
    assert goldman_role_to_job(_item("Internal Audit, Data Analytics, Vice President")) is None


def test_unposted_role_is_skipped():
    assert goldman_role_to_job(_item("Vice President, Product Management", status="CLOSED")) is None


def test_posting_date_comes_from_last_posted_date():
    # Without it the board treats the first scrape as the posting date.
    job = goldman_role_to_job(_item("Vice President, AI Product Manager"))
    assert job["posted"] == TODAY[:10]
    assert goldman_role_to_job(_item("Vice President, AI Product Manager", posted=None))["posted"] == "Unknown"


def test_posting_older_than_recency_window_is_skipped():
    # 184943 was posted 2026-09-24; on 10/6 it is outside the 2-day board window.
    old = (datetime.now(timezone.utc) - timedelta(days=12)).strftime("%Y-%m-%dT19:56:16.648Z")
    assert goldman_role_to_job(_item("Vice President, AI Product Manager", posted=old)) is None
