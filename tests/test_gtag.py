"""Google Ads tag: base install on every page, CSP nonce, and the one-time
sign-up conversion event."""
import re


def test_homepage_has_google_tag(client):
    body = client.get("/").get_data(as_text=True)
    assert "googletagmanager.com/gtag/js?id=AW-1001356637" in body
    assert "gtag('config', 'AW-1001356637')" in body


def test_csp_allows_tag_and_inline_nonce_matches(client):
    resp = client.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "https://www.googletagmanager.com" in csp
    body = resp.get_data(as_text=True)
    csp_nonce = re.search(r"'nonce-([A-Za-z0-9_-]+)'", csp)
    inline_nonce = re.search(r'<script nonce="([A-Za-z0-9_-]+)"', body)
    assert csp_nonce and inline_nonce
    # The inline gtag init only runs if its nonce matches the CSP nonce.
    assert csp_nonce.group(1) == inline_nonce.group(1)


def test_conversion_event_absent_without_label(client):
    # Until GOOGLE_ADS_SIGNUP_LABEL is configured, no conversion event renders.
    assert "'send_to'" not in client.get("/").get_data(as_text=True)


def test_signup_fires_conversion_once_when_label_set(app, client, db_session):
    app.config["GOOGLE_ADS_SIGNUP_LABEL"] = "TESTLABEL123"
    try:
        r = client.post(
            "/sign-in",
            data={
                "email": "gtaguser@example.com",
                "password": "Str0ng-Pass-9x",
                "confirm_password": "Str0ng-Pass-9x",
            },
            follow_redirects=True,
        )
        body = r.get_data(as_text=True)
        # Fires exactly once on the first post-signup page.
        assert body.count("AW-1001356637/TESTLABEL123") == 1
        # Flag consumed — a subsequent page must not re-fire.
        assert "AW-1001356637/TESTLABEL123" not in client.get("/").get_data(as_text=True)
    finally:
        app.config["GOOGLE_ADS_SIGNUP_LABEL"] = ""
