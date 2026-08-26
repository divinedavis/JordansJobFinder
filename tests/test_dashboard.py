"""Dashboard rendering + nav regressions."""


def test_dashboard_renders_for_logged_in_user(signed_in_client):
    response = signed_in_client.get("/dashboard")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Private Jobs" in body


def test_dashboard_has_no_heading_blurb(signed_in_client):
    """The heading and the tab description paragraph were removed — regression guard."""
    response = signed_in_client.get("/dashboard")
    body = response.get_data(as_text=True)
    assert "Your current job matches" not in body
    assert "Product manager, program manager, and project manager jobs" not in body


def test_dashboard_does_not_link_to_settings(signed_in_client):
    """Settings was removed from the top nav — regression guard."""
    response = signed_in_client.get("/dashboard")
    body = response.get_data(as_text=True)
    assert ">Settings</a>" not in body, "Settings link should be gone from the nav"
    assert "Open Settings" not in body, "Open Settings button should be gone from dashboard"


def test_home_does_not_link_to_settings(client):
    response = client.get("/")
    body = response.get_data(as_text=True)
    assert ">Settings</a>" not in body


def test_new_signup_does_not_see_no_saved_search_panel(signed_in_client):
    """Open access: signup auto-seeds a SavedSearch, so the empty-state panel
    must never appear for a fresh user."""
    response = signed_in_client.get("/dashboard")
    body = response.get_data(as_text=True)
    assert "Setting up your matches" not in body
    assert "No saved search yet" not in body


def test_nav_includes_profile_link(signed_in_client):
    response = signed_in_client.get("/dashboard")
    body = response.get_data(as_text=True)
    assert "/profile" in body
    assert ">Profile</a>" in body


def test_nav_has_mobile_hamburger(signed_in_client):
    """The topbar must carry the CSS-only hamburger (checkbox + label) so nav
    links collapse instead of running off small screens."""
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert 'id="nav-toggle"' in body
    assert 'for="nav-toggle"' in body
    assert body.count("nav-toggle-bar") >= 3


def test_dashboard_role_pill_opens_the_role_picker(signed_in_client):
    """The active role pill IS the "change my role" control. Before 2026-08-26
    it linked back to the tab you were already on, and /search wasn't in the
    nav — so there was no way to switch roles from the UI at all."""
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "/search" in body
    assert "Change role" in body


def test_dashboard_does_not_claim_the_search_locks(signed_in_client):
    """Roles switch freely now — no lock copy anywhere on the board."""
    body = signed_in_client.get("/dashboard").get_data(as_text=True).lower()
    assert "locks for 30 days" not in body
    assert "your search is locked" not in body
