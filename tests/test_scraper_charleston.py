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


def test_charleston_is_a_first_class_metro():
    """Charleston used to reach the board only through the 'extra city'
    mechanism — a user had to pick it, and postings were tagged city='extra'.
    Since 2026-07-21 it's one of the 29 built-in metros (SC top-10 keep-list),
    so it resolves directly and no longer depends on anyone's saved search."""
    import scraper

    for active in (["Charleston, SC"], []):
        scraper.ACTIVE_EXTRA_CITIES = active
        assert scraper.infer_pm_city_or_extra("Charleston, SC") == "charleston-sc"
        assert scraper.infer_pm_city_or_extra("North Charleston, SC") == "charleston-sc"
    scraper.ACTIVE_EXTRA_CITIES = []
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
