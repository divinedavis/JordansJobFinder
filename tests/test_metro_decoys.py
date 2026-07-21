"""Guards for place names that merely contain a metro's token.

Skechers' Manhattan Beach, CA headquarters role showed up on the New York
board on 2026-07-21 because NYC's bare "manhattan" pattern matched first.
"""
import scraper
import scraper_finance
import scraper_hr
import scraper_it
import scraper_sales
import scraper_scm
from metro_decoys import strip_decoys


def test_manhattan_beach_is_los_angeles_not_new_york():
    assert scraper.infer_pm_city("Manhattan Beach, CA") == "la"
    assert not scraper.is_nyc("Manhattan Beach, CA")


def test_real_new_york_locations_still_match():
    for loc in ("New York, NY", "Manhattan, NY", "Brooklyn, NY",
                "NYC", "Jersey City, NJ", "New York, New York"):
        assert scraper.is_nyc(loc), loc
        assert scraper.infer_pm_city(loc) == "nyc", loc


def test_minnesota_brooklyns_are_not_new_york():
    for loc in ("Brooklyn Park, MN", "Brooklyn Center, MN"):
        assert not scraper.is_nyc(loc), loc


def test_washington_state_and_pa_are_not_dc():
    assert not scraper.is_dc("Washington, PA")
    assert not scraper.is_dc("Port Washington, NY")
    assert scraper.is_dc("Washington, DC")


def test_strip_decoys_leaves_other_metros_untouched():
    # LA must still see the phrase NYC had stripped.
    assert "manhattan beach" in strip_decoys("manhattan beach, ca", "la")
    assert "manhattan beach" not in strip_decoys("manhattan beach, ca", "nyc")


def test_vertical_scrapers_share_the_guard():
    # scraper_it is deliberately scoped to PA + Florida, so it has no "nyc"
    # metro to mis-claim — the rest all carry a bare "manhattan" pattern.
    for module in (scraper_hr, scraper_finance, scraper_sales, scraper_scm):
        assert module.infer_city("Manhattan Beach, CA") != "nyc", module.__name__
        assert module.infer_city("New York, NY") == "nyc", module.__name__
    assert scraper_it.infer_city("Manhattan Beach, CA") != "nyc"
