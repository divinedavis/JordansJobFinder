"""Matching logic — superuser sees wide scope, regular users see their saved search."""
import os

from app.matching import (
    experience_at_least,
    experience_bucket_matches,
    is_superuser_email,
    match_job_for_user,
    salary_meets_minimum,
    title_is_entry_level_finance,
    title_is_entry_level_sales,
    title_matches,
    title_matches_superuser_scope,
)
from app.parsing import ParsedExperience, parse_experience_years


# Real retail/store-floor/manufacturing titles that leaked into the finance and
# sales verticals — these must be rejected so only corporate roles remain.
NON_CORPORATE_TITLES = [
    "Merchandise Associate",
    "Retail Sales Associate",
    "Sales Floor Associate",
    "5am Stockroom Associate",
    "Store Cleaning Associate",
    "Loss Prevention Customer Service Associate",
    "Xfinity Retail Service Associate - Bilingual Required",
    "Hershey's Part-Time Territory Sales Associate (Dallas Metro)",
    "Temporary Sales Associate",
    "Parts Sales Associate",
    "Production Associate",
]

# Corporate finance/sales titles that must keep matching.
CORPORATE_FINANCE_TITLES = [
    "Financial Analyst",
    "Credit Analyst II",
    "Equity Research Associate",
    "Investment Banking Analyst",
]
CORPORATE_SALES_TITLES = [
    "Sales Development Representative",
    "Business Development Representative",
    "Account Executive",
    "Inside Sales Representative",
]


def test_finance_rejects_non_corporate_titles():
    for title in NON_CORPORATE_TITLES:
        assert title_is_entry_level_finance(title) is False, title


def test_sales_rejects_non_corporate_titles():
    for title in NON_CORPORATE_TITLES:
        assert title_is_entry_level_sales(title) is False, title


def test_finance_keeps_corporate_titles():
    for title in CORPORATE_FINANCE_TITLES:
        assert title_is_entry_level_finance(title) is True, title


def test_sales_keeps_corporate_titles():
    for title in CORPORATE_SALES_TITLES:
        assert title_is_entry_level_sales(title) is True, title


def test_is_superuser_email_open_access():
    # Open access: any signed-in user is treated as superuser. Empty / None
    # is still falsy so the gates correctly reject unauthenticated callers.
    assert is_superuser_email(os.environ["SUPERUSER_EMAIL"]) is True
    assert is_superuser_email("someone-else@example.com") is True
    assert is_superuser_email(None) is False
    assert is_superuser_email("") is False
    assert is_superuser_email("   ") is False


def test_title_matches_basic_keywords():
    assert title_matches("Senior Product Manager", "technical-product-manager") is True
    assert title_matches("Program Manager II", "technical-program-manager") is True
    assert title_matches("Software Engineer", "technical-product-manager") is False


def test_title_matches_excludes_governance():
    assert title_matches("Data Governance Program Manager", "technical-program-manager") is False


def test_title_matches_superuser_scope_accepts_both_roles():
    assert title_matches_superuser_scope("Senior Product Manager") is True
    assert title_matches_superuser_scope("Technical Program Manager") is True
    assert title_matches_superuser_scope("Software Engineer") is False


def test_experience_bucket_matches_within_range():
    parsed = ParsedExperience(min_years=5, max_years=8)
    assert experience_bucket_matches("3-6", parsed) is True
    assert experience_bucket_matches("7-9", parsed) is True
    assert experience_bucket_matches("10+", parsed) is False


def test_experience_at_least_threshold():
    assert experience_at_least(5, ParsedExperience(min_years=6, max_years=None)) is True
    assert experience_at_least(5, ParsedExperience(min_years=3, max_years=4)) is False
    assert experience_at_least(5, ParsedExperience(min_years=None, max_years=None)) is False


def test_salary_meets_minimum_handles_missing_values():
    assert salary_meets_minimum(None, None, 180_000) is True
    assert salary_meets_minimum(150_000, None, 180_000) is False
    assert salary_meets_minimum(None, 200_000, 180_000) is True
    assert salary_meets_minimum(None, 100_000, 180_000) is False


def test_match_job_for_user_superuser_branch():
    superuser = os.environ["SUPERUSER_EMAIL"]
    description = "Looking for a leader with 8+ years of product management experience."
    assert match_job_for_user(
        title_slug="technical-product-manager",
        experience_bucket="0-2",  # ignored on superuser branch
        title="Senior Product Manager - Platform",
        description=description,
        salary_min=200_000,
        salary_max=250_000,
        user_email=superuser,
    ) is True

    # Salary below the $180K superuser floor is rejected.
    assert match_job_for_user(
        title_slug="technical-product-manager",
        experience_bucket="0-2",
        title="Senior Product Manager",
        description=description,
        salary_min=120_000,
        salary_max=140_000,
        user_email=superuser,
    ) is False

    # Too junior — below the 5-year floor.
    assert match_job_for_user(
        title_slug="technical-product-manager",
        experience_bucket="0-2",
        title="Junior Product Manager",
        description="Looking for someone with 2 years of experience.",
        salary_min=200_000,
        salary_max=250_000,
        user_email=superuser,
    ) is False


def test_open_access_any_signed_in_user_sees_superuser_scope():
    # Regression for "open it up so anyone who signs up sees what I see":
    # a non-superuser email still gets the wide PM/PgM 5+yr $180K+ branch.
    description = "Looking for 8+ years of product management experience."
    assert match_job_for_user(
        title_slug="technical-program-manager",  # ignored on superuser branch
        experience_bucket="0-2",                 # ignored on superuser branch
        title="Senior Product Manager",
        description=description,
        salary_min=200_000,
        salary_max=250_000,
        user_email="newuser@example.com",
    ) is True

    # No user email → falls back to the saved-search filter (regular branch).
    assert match_job_for_user(
        title_slug="technical-product-manager",
        experience_bucket="3-6",
        title="Software Engineer",
        description="Requires 4 years of experience.",
        user_email=None,
    ) is False


def test_parse_experience_years_finds_minimum():
    parsed = parse_experience_years("Senior Product Manager", "8+ years of experience required.")
    assert parsed.min_years is not None
    assert parsed.min_years >= 8
