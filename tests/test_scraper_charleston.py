"""Charleston SC employer coverage + the NYC $1B-revenue floor.

Guards the 2026-07-07 changes: five Charleston-area employers added to
WORKDAY_MULTI (so their Charleston postings surface via the extra-city
inference), and 22 sub-$1B companies removed from the NYC watchlist.
"""


def test_charleston_employers_in_workday_multi():
    import scraper

    multi = {tenant: site for _, tenant, _, site in scraper.WORKDAY_MULTI}
    for tenant in ("musc", "ingevity", "boeing", "southstatebank", "godirect"):
        assert tenant in multi, f"Charleston employer {tenant} missing from WORKDAY_MULTI"


def test_boeing_moved_from_percity_to_multi():
    """Boeing is fetched once (multi) instead of 3x per-city, and now covers
    its Charleston 787 plant via per-posting inference."""
    import scraper

    percity_boeing = [e for e in scraper.WORKDAY_COMPANIES if e[1] == "boeing"]
    assert percity_boeing == [], "Boeing should no longer be a per-city entry"
    assert any(t == "boeing" for _, t, _, _ in scraper.WORKDAY_MULTI)


def test_charleston_extra_city_inference_tags_charleston():
    """A multi-list posting in Charleston is tagged city='extra' only when a
    user has 'Charleston, SC' on their saved search."""
    import scraper

    scraper.ACTIVE_EXTRA_CITIES = ["Charleston, SC"]
    assert scraper.infer_pm_city_or_extra("Charleston, SC") == "extra"
    assert scraper.infer_pm_city_or_extra("North Charleston, SC") == "extra"
    # Without the city active, a Charleston posting is dropped (returns None).
    scraper.ACTIVE_EXTRA_CITIES = []
    assert scraper.infer_pm_city_or_extra("Charleston, SC") is None
    # A built-in metro is unaffected either way.
    assert scraper.infer_pm_city_or_extra("New York, NY") == "nyc"


def test_sub_1b_companies_removed_from_nyc():
    """The 22 under-$1B companies are gone from every NYC-tagged list."""
    import scraper

    nyc_tokens = (
        {e[1] for e in scraper.WORKDAY_COMPANIES if e[-1] == "nyc"}
        | {e[1] for e in scraper.GREENHOUSE_COMPANIES if e[-1] == "nyc"}
        | {e[1] for e in scraper.LEVER_COMPANIES if e[-1] == "nyc"}
    )
    removed = [
        "airtable", "aqr", "brex", "capstoneinvestmentadvisors", "discord",
        "exoduspoint", "fiveringsllc", "gemini", "gitlab", "jumptrading",
        "justworks", "lonepinecapital", "magnetar", "marqeta", "marshallwace",
        "pdtpartners", "plaid", "schonfeld", "squarepointcapital",
        "towerresearchcapital", "waymo", "worldquant",
    ]
    still_present = [tok for tok in removed if tok in nyc_tokens]
    assert not still_present, f"sub-$1B companies still NYC-tagged: {still_present}"


def test_large_nyc_companies_retained():
    """Sanity: the $1B+ NYC names stay on the watchlist."""
    import scraper

    nyc_tokens = (
        {e[1] for e in scraper.WORKDAY_COMPANIES if e[-1] == "nyc"}
        | {e[1] for e in scraper.GREENHOUSE_COMPANIES if e[-1] == "nyc"}
        | {e[1] for e in scraper.LEVER_COMPANIES if e[-1] == "nyc"}
    )
    for keep in ("blackrock", "ms", "mastercard", "citadel", "figma", "coinbase"):
        assert keep in nyc_tokens, f"{keep} was wrongly removed from NYC"
