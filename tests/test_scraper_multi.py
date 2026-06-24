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
