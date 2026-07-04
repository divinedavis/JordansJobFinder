"""Fortune 1000 Houston coverage: the per-city Workday additions and the
Oracle/iCIMS extra-ATS pass (list shape + PM-scope title gate)."""


def test_houston_f1000_workday_entries_present():
    import scraper

    hou = {(t, s) for _, t, _, s, c in scraper.WORKDAY_COMPANIES if c == "houston"}
    for tenant, site in [
        ("plains", "plains"),
        ("corebridgefinancial", "corebridgefinancial"),
        ("westlake", "westlake"),
        ("kbr", "kbr_careers"),
        ("chordenergy", "External"),
        ("sci", "sci"),
        ("stewart", "External"),
        ("oxy", "Corporate"),
        ("comfortsystemsusa", "Corpcareers"),
        ("distributionnow", "DNOW_Careers"),
    ]:
        assert (tenant, site) in hou, f"missing Houston Workday entry {tenant}/{site}"


def test_houston_extra_ats_lists_well_formed():
    import scraper

    assert scraper.HOUSTON_EXTRA_ORACLE, "Oracle list emptied"
    assert scraper.HOUSTON_EXTRA_ICIMS, "iCIMS list emptied"
    for name, host, site in scraper.HOUSTON_EXTRA_ORACLE:
        assert name and host.endswith("oraclecloud.com") and site.startswith("CX")
    for name, subdomain in scraper.HOUSTON_EXTRA_ICIMS:
        assert name and subdomain
    # Same platform functions the finance/sales verticals rely on must exist.
    from scraper_ats_extra import scrape_icims, scrape_oracle  # noqa: F401


def test_houston_extra_pass_uses_pm_title_scope():
    """The extra-ATS candidates must clear the same role + seniority gate as
    every other PM source — no entry-level or non-PM titles."""
    import scraper

    gate = lambda t: scraper.is_target_role(t) and scraper.level_ok(t, "houston")
    assert gate("Senior Product Manager")
    assert gate("Principal Program Manager, LNG Projects")
    assert gate("Vice President, Product Management")
    assert not gate("Product Manager")           # plain title — no seniority signal
    assert not gate("Senior Software Engineer")  # not a PM role
    assert not gate("Director, Program Management")  # director-level excluded
