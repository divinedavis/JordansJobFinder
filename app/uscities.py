"""US cities with population above 50,000, grouped by state.

Vendored from the Census Bureau 2023 population estimates
(sub-est2023.csv, incorporated places + consolidated cities, SUMLEV
162/170/172), cleaned of official-name suffixes ("city", "town",
"(balance)") and aliased where common usage differs ("Boise City" ->
"Boise", "Urban Honolulu" -> "Honolulu"). Vermont and West Virginia have
no place above 50k, so they don't appear.

The canonical city label everywhere in the app is "City, ST".
"""
import json
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "static" / "data" / "us_cities_50k.json"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


@lru_cache(maxsize=1)
def cities_by_state() -> dict:
    """{state abbr: [city, ...]} — only states with a 50k+ place."""
    return json.loads(DATA_PATH.read_text())


@lru_cache(maxsize=1)
def valid_city_labels() -> frozenset:
    """Every selectable 'City, ST' label."""
    return frozenset(
        f"{city}, {st}"
        for st, cities in cities_by_state().items()
        for city in cities
    )


def state_choices() -> list[tuple[str, str]]:
    """(abbr, full name) for states that have at least one 50k+ city,
    ordered by full name for the dropdown."""
    return sorted(
        ((st, STATE_NAMES[st]) for st in cities_by_state()),
        key=lambda pair: pair[1],
    )


def split_label(label: str):
    """'Boise, ID' -> ('Boise', 'ID'); returns (label, '') if malformed."""
    if ", " in (label or ""):
        city, st = label.rsplit(", ", 1)
        if st in STATE_NAMES:
            return city, st
    return label or "", ""
