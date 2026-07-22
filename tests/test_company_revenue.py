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


def test_subsidiaries_report_parent_revenue():
    """Owner's rule: a wholly-owned subsidiary shows its parent's revenue, with
    the parent named so the number isn't misread as the subsidiary's own."""
    assert revenue_for("Waymo") == "$403B (Alphabet)"
    assert "Roche" in revenue_for("Flatiron Health")
    assert "Voya" in revenue_for("Benefitfocus")


def test_gemini_is_the_crypto_exchange_not_google():
    """The greenhouse token 'gemini' is the Winklevoss exchange (NASDAQ: GEMI),
    which is independently public — the parent-company rule must not pull
    Alphabet's revenue in here just because of the name."""
    assert revenue_for("Gemini") == "$180M"
    assert "Alphabet" not in revenue_for("Gemini")


def test_ticker_suffix_is_stripped():
    """Some feeds append the ticker: "Clearwater Analytics (CWAN)"."""
    assert revenue_for("Clearwater Analytics (CWAN)") == revenue_for("Clearwater Analytics")
    assert revenue_for("Clearwater Analytics (CWAN)") is not None


def test_regional_pa_employers_have_figures():
    """These reach York/Lancaster/Harrisburg and nothing else does. They're
    exempt from the revenue bar, but the size hint on the card should still be
    right, and several of them also post in non-exempt metros where the bar
    does apply (Hershey in Dallas, Armstrong in NYC)."""
    for company in ("Armstrong World Industries", "Dentsply Sirona",
                    "Fulton Bank", "WellSpan Health", "The Hershey Company",
                    "Penn National Insurance", "Graham Packaging", "Voith"):
        assert revenue_for(company), company


def test_penn_national_insurance_is_not_the_casino_company():
    """Penn National Insurance is a Harrisburg mutual insurer (~$1.0B).
    Penn Entertainment, formerly Penn National Gaming, is a $6.7B casino
    operator — a different company that the name invites confusing it with."""
    from app.company_revenue import revenue_billions

    assert 0.9 < revenue_billions("Penn National Insurance") < 1.5
