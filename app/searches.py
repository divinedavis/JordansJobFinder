from dataclasses import dataclass
from typing import Optional

from flask import current_app

from .catalog import CITY_LABELS, DEFAULT_CITIES, EXPERIENCE_BUCKETS, TITLE_LABELS
from .matching import is_superuser_email


@dataclass
class SearchValidationResult:
    ok: bool
    error: Optional[str] = None


def valid_title_slug(title_slug: str) -> bool:
    return title_slug in TITLE_LABELS


def valid_experience_bucket(bucket: str) -> bool:
    return any(option["slug"] == bucket for option in EXPERIENCE_BUCKETS)


def valid_city(city: str) -> bool:
    """Whether a saved search may carry this city label.

    The state-grouped picker is gone, but this still has to accept three
    things: the metros we cover, any 50k+ US city (older rows chosen through
    the picker), and RETIRED metro labels — a search written before
    2026-07-21 can still hold "Orlando, FL" or "Florida (other)", and it must
    validate rather than blocking the user out of their own settings page.
    """
    from metros import RETIRED_LABELS

    from .uscities import valid_city_labels
    return (city in valid_city_labels()
            or city in CITY_LABELS.values()
            or city in RETIRED_LABELS.values())


def default_cities() -> list[str]:
    return list(DEFAULT_CITIES)


def requires_paid_city_override(selected_cities: list[str], user_email: Optional[str] = None) -> bool:
    if is_superuser_email(user_email):
        return False
    return selected_cities != default_cities()


def validate_saved_search(
    title_slug: str,
    experience_bucket: str,
    cities: list[str],
    max_cities: int = 3,
) -> SearchValidationResult:
    if not valid_title_slug(title_slug):
        return SearchValidationResult(False, "Choose a supported title from the list.")
    if not valid_experience_bucket(experience_bucket):
        return SearchValidationResult(False, "Choose a valid experience bucket.")
    # At least 3 cities keeps the board useful. There is no longer a paid
    # ceiling — callers pass max_cities=len(the full metro set).
    if len(cities) < current_app.config["PAID_CITY_LIMIT"]:
        return SearchValidationResult(False, "Pick at least three cities.")
    if len(cities) > max_cities:
        return SearchValidationResult(False, f"At most {max_cities} cities.")
    if len(set(city.lower() for city in cities)) != len(cities):
        return SearchValidationResult(False, "Cities must be unique.")
    if any(not valid_city(city) for city in cities):
        return SearchValidationResult(False, "Choose cities from the supported list.")
    return SearchValidationResult(True)


def can_change_search(change_count: int, unlimited_changes_unlocked: bool, user_email: Optional[str] = None) -> bool:
    return (
        is_superuser_email(user_email)
        or unlimited_changes_unlocked
        or change_count < current_app.config["FREE_SEARCH_CHANGE_LIMIT"]
    )


def revert_to_free_cities(saved_search) -> None:
    saved_search.cities = default_cities()
    saved_search.is_paid_city_override = False
