"""Company revenue lookup shown on the dashboard card."""
from app.company_revenue import revenue_for


def test_known_company_returns_revenue():
    assert revenue_for("Marsh McLennan")
    assert revenue_for("Reddit")


def test_lookup_tolerates_city_suffix_and_casing():
    # Scraper employer lists append city tokens; the lookup must strip them.
    assert revenue_for("Marsh McLennan DAL") == revenue_for("Marsh McLennan")
    # Punctuation/casing differences between scraped name and key.
    assert revenue_for("marsh mclennan") == revenue_for("Marsh McLennan")


def test_unknown_company_returns_none():
    assert revenue_for("Totally Made Up Co LLC") is None
    assert revenue_for("") is None
    assert revenue_for(None) is None
