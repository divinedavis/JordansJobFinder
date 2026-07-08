"""Dashboard rendering + nav regressions."""


def test_dashboard_renders_for_logged_in_user(signed_in_client):
    response = signed_in_client.get("/dashboard")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Your current job matches" in body


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
