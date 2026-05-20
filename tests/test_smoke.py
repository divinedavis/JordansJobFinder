"""Endpoint reachability — every public + auth-gated route must respond cleanly."""


def test_home_renders(client):
    response = client.get("/")
    assert response.status_code == 200


def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200


def test_signin_page_renders(client):
    response = client.get("/sign-in")
    assert response.status_code == 200


def test_dashboard_redirects_when_unauthenticated(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/sign-in" in response.headers["Location"]


def test_settings_redirects_when_unauthenticated(client):
    # /settings route still exists for now — must not 500.
    response = client.get("/settings")
    assert response.status_code in (200, 302)


def test_billing_redirects_when_unauthenticated(client):
    response = client.get("/billing")
    assert response.status_code in (200, 302)


def test_matches_redirects_to_dashboard(client):
    response = client.get("/matches")
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]


def test_search_redirects_when_unauthenticated(client):
    response = client.get("/search")
    assert response.status_code in (200, 302)
