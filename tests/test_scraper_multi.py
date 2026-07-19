"""Regression guards for the $1B+ multi-metro scraper additions.

These cover the pure logic only (no network): the metro-inference helper and
the integrity of the GREENHOUSE_MULTI / LEVER_MULTI / WORKDAY_MULTI lists.
"""
import scraper


def test_infer_pm_city_maps_known_locations():
    assert scraper.infer_pm_city("New York, NY") == "nyc"
    assert scraper.infer_pm_city("Atlanta, GA") == "atlanta"
    assert scraper.infer_pm_city("Miami, FL") == "miami"
    assert scraper.infer_pm_city("Dallas, TX") == "dallas"
    assert scraper.infer_pm_city("Houston, TX") == "houston"
    assert scraper.infer_pm_city("Washington, DC") == "dc"
    assert scraper.infer_pm_city("Los Angeles, CA") == "la"


def test_infer_pm_city_returns_none_for_unsupported():
    assert scraper.infer_pm_city("Remote - Canada") is None
    assert scraper.infer_pm_city("Seattle, WA") is None
    assert scraper.infer_pm_city("") is None


def test_infer_pm_city_handles_multi_location_strings():
    # Greenhouse boards often list several offices in one string; first
    # supported metro should win.
    assert scraper.infer_pm_city("San Francisco, CA | New York, NY") == "nyc"


def test_multi_lists_are_nonempty_and_well_formed():
    assert len(scraper.GREENHOUSE_MULTI) > 50
    assert len(scraper.WORKDAY_MULTI) > 40
    assert len(scraper.LEVER_MULTI) >= 1
    for name, token in scraper.GREENHOUSE_MULTI:
        assert name and token
    for name, token in scraper.LEVER_MULTI:
        assert name and token
    for name, tenant, ver, site in scraper.WORKDAY_MULTI:
        assert name and tenant and site and isinstance(ver, int)


def test_multi_tokens_do_not_duplicate_per_city_lists():
    # The multi lists exist precisely to avoid per-city duplication; make sure a
    # token/tenant added to a multi list isn't already covered per-city.
    per_city_gh = {t.lower() for _, t, _ in scraper.GREENHOUSE_COMPANIES}
    per_city_lever = {t.lower() for _, t, _ in scraper.LEVER_COMPANIES}
    per_city_wd = {t.lower() for _, t, _, _, _ in scraper.WORKDAY_COMPANIES}
    assert not ({t.lower() for _, t in scraper.GREENHOUSE_MULTI} & per_city_gh)
    assert not ({t.lower() for _, t in scraper.LEVER_MULTI} & per_city_lever)
    assert not ({t.lower() for _, t, _, _ in scraper.WORKDAY_MULTI} & per_city_wd)


# ── Top-10-city metros (2026-07-19) ──────────────────────────────────────────

def test_infer_pm_city_new_top10_metros():
    assert scraper.infer_pm_city("Chicago, IL") == "chicago"
    assert scraper.infer_pm_city("Deerfield, IL") == "chicago"
    assert scraper.infer_pm_city("Phoenix, AZ") == "phoenix"
    assert scraper.infer_pm_city("Scottsdale, AZ") == "phoenix"
    assert scraper.infer_pm_city("San Antonio, TX") == "san-antonio"
    assert scraper.infer_pm_city("San Diego, CA") == "san-diego"
    assert scraper.infer_pm_city("Carlsbad, CA") == "san-diego"
    assert scraper.infer_pm_city("Jacksonville, FL") == "jacksonville-fl"
    assert scraper.infer_pm_city("Ponte Vedra Beach, FL") == "jacksonville-fl"
    assert scraper.infer_pm_city("Philadelphia, PA") == "philadelphia-pa"
    assert scraper.infer_pm_city("Conshohocken, PA") == "philadelphia-pa"


def test_new_metro_ordering_beats_catchalls():
    # San Antonio must win over Dallas's ", tx"/"texas" catch-alls.
    assert scraper.infer_pm_city("San Antonio, Texas") == "san-antonio"
    # Glendale AZ must win over LA's bare "glendale"; bare Glendale stays LA.
    assert scraper.infer_pm_city("Glendale, AZ") == "phoenix"
    assert scraper.infer_pm_city("Glendale") == "la"
    # Pre-existing guarantees still hold.
    assert scraper.infer_pm_city("Arlington, VA") == "dc"
    assert scraper.infer_pm_city("Houston, TX") == "houston"
    # Rosemont/Deerfield need the IL suffix so PA/FL towns don't leak in.
    assert scraper.infer_pm_city("Rosemont, PA") == "philadelphia-pa"
    assert scraper.infer_pm_city("Deerfield Beach, FL") != "chicago"


def test_top10_wave_present_and_city_labels_complete():
    wd_tenants = {t for _, t, _, _ in scraper.WORKDAY_MULTI}
    for tenant in ("usaa", "mdlz", "citi", "republic", "illumina",
                   "myhrabc", "pgatour", "aresmgmt"):
        assert tenant in wd_tenants, tenant
    gh_tokens = {t for _, t in scraper.GREENHOUSE_MULTI}
    assert {"axon", "fanaticsinc"} <= gh_tokens
    assert "dnb" in {t for _, t in scraper.LEVER_MULTI}
    # Every inferable metro slug must have a display label app-side.
    from app.sync import CITY_DISPLAY
    from app.results import CITY_LABELS as APP_CITY_LABELS
    for slug in scraper.PM_METROS:
        assert slug in scraper.CITY_LABELS, slug
        assert slug in CITY_DISPLAY, slug
        assert slug in APP_CITY_LABELS, slug


def test_top10_wave_companies_have_revenue():
    from app.company_revenue import revenue_for
    for company in ("USAA", "Mondelez", "Cencora", "Illumina", "Republic Services",
                    "Axon", "Fanatics", "Dun & Bradstreet", "Citigroup"):
        assert revenue_for(company), company
