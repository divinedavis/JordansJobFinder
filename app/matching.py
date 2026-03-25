from typing import Optional

from .catalog import CITY_LABELS, SUPERUSER_EMAIL, TITLE_KEYWORDS
from .parsing import ParsedExperience, parse_experience_years


def normalize_text(value: str) -> str:
    import re
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def title_matches(title: str, selected_slug: str) -> bool:
    normalized = normalize_text(title)
    keywords = TITLE_KEYWORDS.get(selected_slug, [])
    return any(keyword in normalized for keyword in keywords)


def title_matches_superuser_scope(title: str) -> bool:
    normalized = normalize_text(title)
    return "product manager" in normalized or "program manager" in normalized

def experience_bucket_matches(bucket: str, parsed: ParsedExperience) -> bool:
    if parsed.min_years is None and parsed.max_years is None:
        return False

    target_ranges = {
        "0-2": (0, 2),
        "3-6": (3, 6),
        "7-9": (7, 9),
        "10+": (10, None),
    }
    target_low, target_high = target_ranges[bucket]
    value_low = parsed.min_years or 0
    value_high = parsed.max_years

    if target_high is None:
        return value_low >= target_low or (value_high is not None and value_high >= target_low)

    if value_high is None:
        return target_low <= value_low <= target_high

    return not (value_high < target_low or value_low > target_high)


def experience_at_least(minimum_years: int, parsed: ParsedExperience) -> bool:
    if parsed.min_years is None and parsed.max_years is None:
        return False
    low = parsed.min_years or 0
    high = parsed.max_years
    return low >= minimum_years or (high is not None and high >= minimum_years)


def salary_meets_minimum(
    salary_min: Optional[int],
    salary_max: Optional[int],
    minimum_salary: int,
) -> bool:
    if salary_min is None and salary_max is None:
        return True
    if salary_max is not None:
        return salary_max >= minimum_salary
    if salary_min is not None:
        return salary_min >= minimum_salary
    return True


def match_job(title_slug: str, experience_bucket: str, title: str, description: str) -> bool:
    if not title_matches(title, title_slug):
        return False

    parsed = parse_experience_years(title, description)
    return experience_bucket_matches(experience_bucket, parsed)


def choose_cities(city_1: str, city_2: str, city_3: str) -> list[str]:
    return [city for city in [city_1, city_2, city_3] if city]


def city_from_slug(city_slug: str) -> str:
    return CITY_LABELS.get(city_slug, city_slug)


def is_superuser_email(email: Optional[str]) -> bool:
    return (email or "").strip().lower() == SUPERUSER_EMAIL


def match_job_for_user(
    title_slug: str,
    experience_bucket: str,
    title: str,
    description: str,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    user_email: Optional[str] = None,
) -> bool:
    parsed = parse_experience_years(title, description)
    if is_superuser_email(user_email):
        return (
            title_matches_superuser_scope(title)
            and experience_at_least(8, parsed)
            and salary_meets_minimum(salary_min, salary_max, 180000)
        )

    if not title_matches(title, title_slug):
        return False
    return experience_bucket_matches(experience_bucket, parsed)
