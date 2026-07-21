"""The paid city tiers are gone (2026-07-21).

This file used to assert the 3 free / 5 / 10-city plans. Cities stopped being a
product the day every board went to the full metro set, so what's worth
guarding now is that the caps don't creep back — a stale `[:limit]` slice
silently drops metros off someone's board, which is exactly how York PA
vanished from the HR track partway through that migration.

The Stripe plumbing itself is deliberately still present so existing
subscribers can cancel; it just doesn't gate anything.
"""
import pytest

from app.catalog import ALL_CITY_LABELS, VERTICAL_DEFAULT_CITIES


class _User:
    email = "nobody@example.com"


def _sub(city_limit):
    class _S:
        pass
    s = _S()
    s.city_limit = city_limit
    return s


def test_every_account_covers_every_metro():
    from app.routes import city_limit_for

    assert city_limit_for(_User(), _sub(3)) == len(ALL_CITY_LABELS) == 29


def test_a_legacy_paid_row_grants_nothing_extra():
    """A stored city_limit must no longer shrink OR expand coverage."""
    from app.routes import city_limit_for

    limits = {city_limit_for(_User(), _sub(v)) for v in (3, 5, 10, None, 0)}
    assert len(limits) == 1, f"city_limit still influences coverage: {limits}"


def test_pro_features_are_free_for_everyone():
    from app.routes import is_pro

    assert is_pro(_User(), _sub(3)) is True


def test_every_vertical_covers_the_full_metro_set():
    for vertical, cities in VERTICAL_DEFAULT_CITIES.items():
        assert list(cities) == list(ALL_CITY_LABELS), vertical


def test_validation_no_longer_imposes_a_three_city_ceiling(app):
    """The old default was max_cities=3; the full set must validate."""
    from app.searches import validate_saved_search

    with app.app_context():
        result = validate_saved_search(
            "technical-product-manager", "3-6", list(ALL_CITY_LABELS),
            max_cities=len(ALL_CITY_LABELS),
        )
        assert result.ok is True, result.error


@pytest.mark.parametrize("path", ["/search", "/profile"])
def test_no_city_upgrade_pitch_remains(signed_in_client, path):
    body = signed_in_client.get(path, follow_redirects=True).get_data(as_text=True)
    for pitch in ("Upgrade to 5 cities", "10 cities for $19.99",
                  "Need more?", "cities on your current plan"):
        assert pitch not in body, f"{path} still sells city tiers: {pitch!r}"
