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


def test_suffix_stripping_stops_at_the_first_match():
    """Regression: 'Inc' is a suffix token too, so stripping straight to the
    shortest form turned "HP Inc HOU" into "HP" — no row, blank size hint on
    every HP card. The lookup must try each intermediate form."""
    assert revenue_for("HP Inc HOU") == revenue_for("HP Inc")
    assert revenue_for("HP Inc HOU") is not None


def test_every_configured_employer_has_a_revenue_row():
    """Guard: adding an employer without a revenue row ships a blank size hint.

    Wayve is the one sanctioned exception — its filings describe it as
    pre-revenue R&D, and the module's convention is no row rather than a
    made-up number. Add to the allowlist only for the same reason.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    allowed_without_revenue = {"Wayve"}

    names = set()
    for fname in ("scraper.py", "scraper_finance.py", "scraper_sales.py",
                  "scraper_it.py", "scraper_hr.py", "scraper_scm.py",
                  "scraper_sc_employers.py"):
        for match in re.finditer(r'^\s*\("([^"]+)",', (root / fname).read_text(), re.M):
            names.add(match.group(1))

    missing = sorted(
        n for n in names
        if revenue_for(n) is None and n not in allowed_without_revenue
    )
    assert not missing, f"employers with no revenue row: {missing}"
