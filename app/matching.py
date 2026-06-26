from typing import Optional

from .catalog import CITY_LABELS, SUPERUSER_EMAIL, TITLE_KEYWORDS, TITLE_VERTICALS

EXCLUDE_TITLES = ["governance"]
# Companies the user never wants to see on the dashboard, matched
# case-insensitively against the normalized company name.
EXCLUDE_COMPANIES = {"scale ai", "google"}
# Title keywords that disqualify a finance role as entry-level
FINANCE_SENIOR_NEGATIVE = (
    "senior", "principal", "lead", "staff vp", "vp ", " vp",
    "director", "head of", "chief", "managing director",
    "vice president",
)
# Title keywords that disqualify a sales role as entry-level. "manager" stays
# in (rules out plain "Sales Manager" / "Account Manager"); "engineer" is NOT
# here because "Sales Engineer" / "Solutions Engineer" are valid entry roles.
SALES_SENIOR_NEGATIVE = (
    "senior", "principal", "lead", "staff vp", "vp ", " vp",
    "director", "head of", "chief", "managing director",
    "vice president", "manager", "managing",
)
from .parsing import ParsedExperience, parse_experience_years


def normalize_text(value: str) -> str:
    import re
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _title_excluded(normalized: str) -> bool:
    return any(term in normalized for term in EXCLUDE_TITLES)


def company_excluded(company: str) -> bool:
    return normalize_text(company) in EXCLUDE_COMPANIES


def title_matches(title: str, selected_slug: str) -> bool:
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    keywords = TITLE_KEYWORDS.get(selected_slug, [])
    return any(keyword in normalized for keyword in keywords)


def title_matches_superuser_scope(title: str) -> bool:
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    return "product manage" in normalized or "program manage" in normalized


def title_is_entry_level_finance(title: str) -> bool:
    """Heuristic: title contains analyst/associate vocabulary and is NOT
    flagged as senior/director-level."""
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    if any(neg in normalized for neg in FINANCE_SENIOR_NEGATIVE):
        return False
    finance_kws = TITLE_KEYWORDS.get("entry-finance-any", [])
    if any(kw in normalized for kw in finance_kws):
        return True
    # Catch the broader analyst/associate vocabulary as a fallback
    return "analyst" in normalized or "associate" in normalized


def title_is_entry_level_sales(title: str) -> bool:
    """Heuristic mirror of title_is_entry_level_finance for sales roles."""
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    if any(neg in normalized for neg in SALES_SENIOR_NEGATIVE):
        return False
    sales_kws = TITLE_KEYWORDS.get("entry-sales-any", [])
    if any(kw in normalized for kw in sales_kws):
        return True
    return False

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
    # Open access: every signed-in user gets the wide superuser scope
    # (PM + PgM, 5+ years, $180K+) and bypasses the billing gates.
    return bool((email or "").strip())


def match_job_for_user(
    title_slug: str,
    experience_bucket: str,
    title: str,
    description: str,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    user_email: Optional[str] = None,
) -> bool:
    vertical = TITLE_VERTICALS.get(title_slug, "pm")
    parsed = parse_experience_years(title, description)

    if vertical == "finance":
        # Finance: title heuristic + entry-level seniority; no salary floor
        if not title_is_entry_level_finance(title):
            return False
        if title_slug != "entry-finance-any" and not title_matches(title, title_slug):
            return False
        # If experience is parseable, require it to fit the bucket (defaults to 0-2)
        if parsed.min_years is not None or parsed.max_years is not None:
            return experience_bucket_matches(experience_bucket or "0-2", parsed)
        return True

    if vertical == "sales":
        # Sales: same shape as finance — title heuristic + entry-level seniority,
        # no salary floor, optional per-track keyword check.
        if not title_is_entry_level_sales(title):
            return False
        if title_slug != "entry-sales-any" and not title_matches(title, title_slug):
            return False
        if parsed.min_years is not None or parsed.max_years is not None:
            return experience_bucket_matches(experience_bucket or "0-2", parsed)
        return True

    # PM/PgM (existing logic)
    if is_superuser_email(user_email):
        return (
            title_matches_superuser_scope(title)
            and experience_at_least(5, parsed)
            and salary_meets_minimum(salary_min, salary_max, 180000)
        )

    if not title_matches(title, title_slug):
        return False
    return experience_bucket_matches(experience_bucket, parsed)
