"""Guards for the shared metro registry (metros.py).

Substring matching over a 29-metro table is collision-prone, so every case
below is one that actually bit or nearly bit.
"""
import pytest

from metros import (ALL_METROS, LABELS, MATCH_ORDER, PATTERNS, STATE_FALLBACK,
                    TOP_20, infer_metro, matches_metro)


def test_registry_is_internally_consistent():
    assert set(MATCH_ORDER) == set(PATTERNS) == set(LABELS)
    assert len(TOP_20) == 20
    assert len(ALL_METROS) == 29  # top 20 + 3 PA + 6 SC
    assert len(set(MATCH_ORDER)) == len(MATCH_ORDER), "duplicate slug"


@pytest.mark.parametrize("location,expected", [
    ("New York, NY", "nyc"),
    ("Los Angeles, CA", "la"),
    ("Boston, MA", "boston"),
    ("Seattle, WA", "seattle"),
    ("Minneapolis, MN", "minneapolis"),
    ("St. Paul, MN", "minneapolis"),
    ("Denver, CO", "denver"),
    ("Detroit, MI", "detroit"),
    ("Riverside, CA", "riverside"),
    ("San Francisco, CA", "san-francisco"),
    ("Tampa, FL", "tampa-fl"),
    ("Baltimore, MD", "baltimore-md"),
    ("Sumter, SC", "sumter-sc"),
    ("Florence, SC", "florence-sc"),
])
def test_each_metro_matches_its_own_name(location, expected):
    assert infer_metro(location) == expected


@pytest.mark.parametrize("location,expected", [
    # Same city name, different state — the true metro must win.
    ("Manhattan Beach, CA", "la"),          # not nyc
    ("Brooklyn Park, MN", "minneapolis"),   # not nyc
    ("Riverside, IL", "chicago"),           # not riverside
    ("Denver, PA", "lancaster-pa"),         # not denver — Lancaster County
    ("Lancaster, CA", "la"),                # not lancaster-pa
    ("Columbia, MD", "baltimore-md"),       # not columbia-sc
    ("Oakland Park, FL", "miami"),          # not san-francisco
    ("Glendale, AZ", "phoenix"),            # not la
    ("Glendale, CA", "la"),                 # not phoenix
    ("Arlington, VA", "dc"),                # not dallas
    ("Arlington, TX", "dallas"),            # not dc
    ("Ontario, CA", "riverside"),           # not Canada
])
def test_cross_state_collisions_resolve_to_the_right_metro(location, expected):
    assert infer_metro(location) == expected


@pytest.mark.parametrize("location", [
    "Charleston, WV",
    "Florence, KY",
    "Detroit Lakes, MN",
    "Remote - Canada",
    "",
])
def test_lookalike_places_match_nothing(location):
    assert infer_metro(location) == ""


@pytest.mark.parametrize("location", [
    "San Antonio, TX",
    "Jacksonville, FL",
    "Orlando, FL",
])
def test_dropped_metros_are_excluded_not_relabelled(location):
    """Regression: these were dropped on 2026-07-21. A bare ", tx" catch-all in
    Dallas's pattern list would have silently relabelled every San Antonio job
    as Dallas instead of excluding it."""
    assert infer_metro(location) == ""


@pytest.mark.parametrize("location", ["Austin, TX", "Savannah, GA", "Tucson, AZ"])
def test_state_catch_alls_never_fire_during_inference(location):
    """A job elsewhere in Texas/Georgia/Arizona is not a Dallas/Atlanta/Phoenix
    job. The bare state tokens are per-city-scrape only."""
    assert infer_metro(location) == ""


def test_state_fallback_is_available_to_per_city_callers():
    # Per-city scraping already knows the target metro, so ", TX" is safe there.
    assert matches_metro("Austin, TX", "dallas", allow_state_fallback=True)
    assert not matches_metro("Austin, TX", "dallas", allow_state_fallback=False)
    assert set(STATE_FALLBACK) <= set(PATTERNS)


def test_allowed_subset_restricts_inference():
    # Verticals that cover fewer metros pass an allowlist.
    assert infer_metro("Boston, MA", allowed={"nyc", "philadelphia-pa"}) == ""
    assert infer_metro("Boston, MA", allowed={"boston", "nyc"}) == "boston"


def test_sc_metros_cover_the_states_ten_largest_cities():
    """The keep-list is 'top 10 SC cities'; eight fall inside existing metros."""
    for city, metro in [
        ("Charleston, SC", "charleston-sc"),
        ("Columbia, SC", "columbia-sc"),
        ("North Charleston, SC", "charleston-sc"),
        ("Mount Pleasant, SC", "charleston-sc"),
        ("Rock Hill, SC", "rock-hill-sc"),
        ("Greenville, SC", "greenville-sc"),
        ("Summerville, SC", "charleston-sc"),
        ("Goose Creek, SC", "charleston-sc"),
        ("Sumter, SC", "sumter-sc"),
        ("Greer, SC", "greenville-sc"),
        ("Florence, SC", "florence-sc"),
    ]:
        assert infer_metro(city) == metro, city


def test_pa_trio_survives():
    for city, metro in [("York, PA", "york-pa"),
                        ("Lancaster, PA", "lancaster-pa"),
                        ("Harrisburg, PA", "harrisburg-pa")]:
        assert infer_metro(city) == metro, city


def test_migration_command_is_registered():
    """The full-metro-coverage migration must stay available: saved searches
    written before 2026-07-21 carry the old 3-city sets, and without running it
    those users keep seeing 3 metros while the code believes they see 29."""
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent / "manage.py").read_text()
    assert '"migrate-full-metro-coverage"' in source
    assert source.count('"migrate-full-metro-coverage"') >= 2  # choice + branch
