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
    # Per-city scraping already knows the target metro, so a location that
    # names ONLY the state is safe to accept there — but never during
    # inference, and never when a city we don't cover is named.
    assert matches_metro(", TX", "dallas", allow_state_fallback=True)
    assert not matches_metro(", TX", "dallas", allow_state_fallback=False)
    assert not matches_metro("Austin, TX", "dallas", allow_state_fallback=True)
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


# ── The per-city state fallback must not claim uncovered cities ──────────────

@pytest.mark.parametrize("location,slug", [
    ("Lubbock, TX, 79407", "dallas"),      # Xcel Energy, 2026-07-21
    ("Amarillo, TX, 79101", "dallas"),
    ("Austin, TX", "dallas"),
    ("Remote - Texas", "dallas"),
    ("Savannah, GA", "atlanta"),
    ("Tucson, AZ", "phoenix"),
])
def test_state_fallback_never_claims_a_named_city(location, slug):
    """A real place name we don't cover must be dropped, not absorbed by the
    big metro in that state. Xcel Energy's Panhandle postings sat on the Dallas
    board for exactly this reason — Lubbock matched Dallas's ", tx"."""
    assert matches_metro(location, slug, allow_state_fallback=True) is False


@pytest.mark.parametrize("location,slug", [
    (", TX", "dallas"),
    ("TX", "dallas"),
    ("Texas", "dallas"),
    ("Georgia", "atlanta"),
    ("GA", "atlanta"),
])
def test_state_fallback_still_covers_state_only_locations(location, slug):
    """Its actual purpose: a per-city scrape where the posting named no city."""
    assert matches_metro(location, slug, allow_state_fallback=True) is True


@pytest.mark.parametrize("location,slug", [
    ("Dallas, TX", "dallas"),
    ("Plano, TX", "dallas"),
    ("Houston, TX", "houston"),
    ("Atlanta, GA", "atlanta"),
    ("Phoenix, AZ", "phoenix"),
])
def test_real_metro_cities_still_match_in_per_city_mode(location, slug):
    assert matches_metro(location, slug, allow_state_fallback=True) is True


def test_multi_location_postings_prefer_a_covered_metro():
    """Workday returns several offices for one req. Xcel's PMO role listed
    Denver, Eau Claire, Minneapolis and Lubbock; the scraper takes the first
    that resolves, so a covered metro must win over the uncovered one."""
    for loc, expected in [("Denver, CO, 80223", "denver"),
                          ("Eau Claire, WI, 54702", ""),
                          ("Minneapolis, MN, 55418", "minneapolis"),
                          ("Lubbock, TX, 79407", "")]:
        assert infer_metro(loc) == expected, loc


# ── Full state names vs postal abbreviations ─────────────────────────────────

@pytest.mark.parametrize("location,expected", [
    ("Arlington, Virginia, United States", "dc"),
    ("Alexandria, Virginia", "dc"),
    ("Seattle, Washington", "seattle"),
    ("Bellevue, Washington", "seattle"),
    ("Boston, Massachusetts, USA", "boston"),
    ("Cambridge, Massachusetts", "boston"),
    ("Denver, Colorado", "denver"),
    ("Arlington, Texas", "dallas"),
])
def test_spelled_out_states_match_the_same_as_abbreviations(location, expected):
    """Workday spells states out; the patterns use postal codes for
    disambiguation. Without normalising, real DC-suburb postings were dropped
    because "arlington, va" never matched "Arlington, Virginia"."""
    assert infer_metro(location) == expected


def test_normalisation_does_not_create_false_matches():
    from metros import normalize_states

    # A city genuinely named Washington/Georgia keeps its own identity — only
    # a state name FOLLOWING A COMMA is rewritten.
    assert normalize_states("washington, dc") == "washington, dc"
    assert infer_metro("WA, Working at Home - Washington") == ""
    assert infer_metro("Austin, Texas") == ""
    # "west virginia" must not be eaten by "virginia".
    assert normalize_states("charleston, west virginia") == "charleston, wv"
    assert infer_metro("Charleston, West Virginia") == ""
