import re
from dataclasses import dataclass
from typing import Optional

from .catalog import CITY_LABELS, SUPERUSER_EMAIL, TITLE_KEYWORDS


YEARS_RANGE_PATTERN = re.compile(
    r"(?P<low>\d+)\s*(?:\+|plus)?\s*(?:-|to)\s*(?P<high>\d+)?\s*years?",
    re.I,
)
YEARS_MIN_PATTERN = re.compile(
    r"(?:at least|minimum of|min\.?|over|more than)?\s*(?P<low>\d+)(?:\+|\s+or\s+more)?\s*years?",
    re.I,
)
YEARS_EMBEDDED_PATTERN = re.compile(
    r"(?:minimum|required|requires|requiring|preferred|preference for|with)\s+(?P<low>\d+)\+?\s*(?:\w+\s+){0,4}?years?",
    re.I,
)


@dataclass
class ParsedExperience:
    min_years: Optional[int] = None
    max_years: Optional[int] = None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def title_matches(title: str, selected_slug: str) -> bool:
    normalized = normalize_text(title)
    keywords = TITLE_KEYWORDS.get(selected_slug, [])
    return any(keyword in normalized for keyword in keywords)


def title_matches_superuser_scope(title: str) -> bool:
    normalized = normalize_text(title)
    return "product manager" in normalized or "program manager" in normalized


def parse_experience_years(*texts: str) -> ParsedExperience:
    combined = " ".join(normalize_text(text) for text in texts if text)
    best = ParsedExperience()

    for match in YEARS_RANGE_PATTERN.finditer(combined):
        low = int(match.group("low"))
        high = match.group("high")
        high_value = int(high) if high else low
        if best.min_years is None or low < best.min_years:
            best.min_years = low
        if best.max_years is None or high_value > best.max_years:
            best.max_years = high_value

    if best.min_years is not None:
        return best

    mins = []
    for match in YEARS_MIN_PATTERN.finditer(combined):
        mins.append(int(match.group("low")))
    for match in YEARS_EMBEDDED_PATTERN.finditer(combined):
        mins.append(int(match.group("low")))
    if mins:
        low = min(mins)
        return ParsedExperience(min_years=low, max_years=None)

    return best


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
