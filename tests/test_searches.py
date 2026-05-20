"""Saved-search validation + paywall logic."""
import os

import pytest

from app.searches import (
    can_change_search,
    default_cities,
    requires_paid_city_override,
    valid_city,
    valid_experience_bucket,
    valid_title_slug,
    validate_saved_search,
)


def test_valid_lookups():
    assert valid_title_slug("technical-product-manager") is True
    assert valid_title_slug("not-a-real-slug") is False
    assert valid_experience_bucket("3-6") is True
    assert valid_experience_bucket("nope") is False
    assert valid_city("New York, NY") is True
    assert valid_city("Atlantis, ZZ") is False


def test_validate_saved_search_happy_path(app):
    with app.app_context():
        result = validate_saved_search(
            "technical-product-manager",
            "3-6",
            ["New York, NY", "Atlanta, GA", "Miami, FL"],
        )
        assert result.ok is True


def test_validate_saved_search_rejects_wrong_city_count(app):
    with app.app_context():
        result = validate_saved_search(
            "technical-product-manager",
            "3-6",
            ["New York, NY"],
        )
        assert result.ok is False


def test_validate_saved_search_rejects_duplicate_cities(app):
    with app.app_context():
        result = validate_saved_search(
            "technical-product-manager",
            "3-6",
            ["New York, NY", "New York, NY", "Miami, FL"],
        )
        assert result.ok is False


def test_requires_paid_city_override_default_cities():
    assert requires_paid_city_override(default_cities()) is False


def test_requires_paid_city_override_custom_cities():
    custom = ["New York, NY", "Atlanta, GA", "Dallas, TX"]
    assert requires_paid_city_override(custom) is True


def test_requires_paid_city_override_superuser_bypass():
    custom = ["New York, NY", "Atlanta, GA", "Dallas, TX"]
    assert requires_paid_city_override(custom, user_email=os.environ["SUPERUSER_EMAIL"]) is False


def test_requires_paid_city_override_open_access_for_any_signed_in_user():
    # Open access: any signed-in user bypasses the city paywall.
    custom = ["New York, NY", "Atlanta, GA", "Dallas, TX"]
    assert requires_paid_city_override(custom, user_email="newuser@example.com") is False


def test_can_change_search_respects_limit_and_unlock(app):
    with app.app_context():
        # Under the free limit.
        assert can_change_search(change_count=0, unlimited_changes_unlocked=False) is True
        # At the free limit but unlocked.
        assert can_change_search(change_count=99, unlimited_changes_unlocked=True) is True
        # Past the free limit, not unlocked.
        assert can_change_search(change_count=99, unlimited_changes_unlocked=False) is False
        # Superuser always allowed.
        assert can_change_search(
            change_count=99,
            unlimited_changes_unlocked=False,
            user_email=os.environ["SUPERUSER_EMAIL"],
        ) is True
        # Open access: any signed-in user is also allowed to change freely.
        assert can_change_search(
            change_count=99,
            unlimited_changes_unlocked=False,
            user_email="newuser@example.com",
        ) is True
