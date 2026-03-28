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
    return city in CITY_LABELS.values()


def default_cities() -> list[str]:
    return list(DEFAULT_CITIES)


def requires_paid_city_override(selected_cities: list[str], user_email: Optional[str] = None) -> bool:
    if is_superuser_email(user_email):
        return False
    return selected_cities != default_cities()


def validate_saved_search(title_slug: str, experience_bucket: str, cities: list[str]) -> SearchValidationResult:
    if not valid_title_slug(title_slug):
        return SearchValidationResult(False, "Choose a supported title from the list.")
    if not valid_experience_bucket(experience_bucket):
        return SearchValidationResult(False, "Choose a valid experience bucket.")
    if len(cities) != current_app.config["PAID_CITY_LIMIT"]:
        return SearchValidationResult(False, "Exactly three cities are required.")
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
    cities = default_cities()
    saved_search.city_1, saved_search.city_2, saved_search.city_3 = cities
    saved_search.is_paid_city_override = False
