"""Goldman Sachs scraper: higher.gs.com GraphQL items -> board jobs."""
from scraper import goldman_role_to_job


def _item(title, corp="Vice President", city="New York", role_id="184943", status="POSTED"):
    return {"roleId": role_id, "corporateTitle": corp, "jobTitle": title, "status": status,
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
