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
