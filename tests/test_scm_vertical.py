"""Supply Chain Management vertical: title heuristic, SC city inference,
no-salary matching, select-a-track flow, and the 7-day board window."""


def test_title_is_scm_accepts_supply_chain_roles():
    from app.matching import title_is_scm

    for title in (
        "Supply Chain Manager",
        "Senior Logistics Analyst",
        "Procurement Specialist",
        "Strategic Sourcing Manager",
        "Demand Planning Analyst",
        "Category Manager, Indirect",
        "Buyer II",
    ):
        assert title_is_scm(title), title


def test_title_is_scm_rejects_unrelated_roles():
    from app.matching import title_is_scm

    for title in (
        "Software Engineer",
        "Registered Nurse",
        "Supply Chain Intern",
        "Financial Analyst",
        "Account Executive",
    ):
        assert not title_is_scm(title), title


def test_scm_scraper_infers_sc_and_nationwide_metros():
    from scraper_scm import infer_city

    assert infer_city("Charleston, SC") == "charleston-sc"
    assert infer_city("North Charleston, SC") == "charleston-sc"
    assert infer_city("Columbia, SC") == "columbia-sc"
    assert infer_city("Greenville, SC") == "greenville-sc"
    assert infer_city("Spartanburg, SC") == "greenville-sc"
    assert infer_city("Rock Hill, SC") == "rock-hill-sc"
    assert infer_city("Fort Mill, SC") == "rock-hill-sc"
    # Nationwide expansion (2026-07-19).
    assert infer_city("Chicago, IL") == "chicago"
    assert infer_city("Phoenix, AZ") == "phoenix"
    # San Antonio was dropped on 2026-07-21 (outside the top 20).
    assert infer_city("San Antonio, TX") == ""
    assert infer_city("Houston, TX") == "houston"
    assert infer_city("Glendale, AZ") == "phoenix"
    assert infer_city("Philadelphia, PA") == "philadelphia-pa"
    assert infer_city("Boston, MA") == "boston"
    assert infer_city("Seattle, WA") == "seattle"
    assert infer_city("Denver, CO") == "denver"
    # Out of scope -> dropped.
    assert infer_city("Charlotte, NC") == ""


def test_verified_sc_1b_employers_are_in_scm_union():
    # The verified >$1B SC employers (probed 200 from the droplet) must feed the
    # SC track so their SC-located jobs surface. Guards against the registry
    # being dropped from the union.
    from scraper_scm import SCM_GREENHOUSE_COMPANIES, SCM_WORKDAY_COMPANIES
    from scraper_sc_employers import SC_GREENHOUSE_1B, SC_WORKDAY_1B

    wd_specs = {(t, v, s) for _, t, v, s in SCM_WORKDAY_COMPANIES}
    for name, tenant, ver, site in SC_WORKDAY_1B:
        assert (tenant, ver, site) in wd_specs, name

    gh_tokens = {tok for _, tok in SCM_GREENHOUSE_COMPANIES}
    for name, token in SC_GREENHOUSE_1B:
        assert token in gh_tokens, name

    # Spot-check a few marquee SC employers made it in by name.
    names = {e[0] for e in SCM_WORKDAY_COMPANIES}
    for marquee in ("Michelin", "Trane Technologies", "Prisma Health", "MUSC"):
        assert marquee in names, marquee


def test_scm_matches_without_salary(app):
    from app.matching import match_job_for_user

    assert match_job_for_user(
        "supply-chain-mgmt", "3-6", "Supply Chain Manager", "",
        None, None, "u@example.com",
    )
    assert not match_job_for_user(
        "supply-chain-mgmt", "3-6", "Marketing Manager", "",
        None, None, "u@example.com",
    )


def test_scm_covers_every_metro_including_south_carolina():
    from app.catalog import ALL_CITY_LABELS, SCM_DEFAULT_CITIES

    assert list(SCM_DEFAULT_CITIES) == list(ALL_CITY_LABELS)
    # SC is the track's original territory and must survive the expansion.
    for sc in ("Charleston, SC", "Columbia, SC", "Greenville, SC",
               "Rock Hill, SC", "Sumter, SC", "Florence, SC"):
        assert sc in SCM_DEFAULT_CITIES


def test_selecting_scm_adds_track_with_every_metro(signed_in_client, db_session):
    from app.models import SavedSearch, User

    resp = signed_in_client.post("/search", data={
        "ack_lock": "1",
        "title_slug": "supply-chain-mgmt", "experience_bucket": "3-6",
    })
    assert resp.status_code == 302
    assert "tab=scm" in resp.headers["Location"]

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "scm"
    ).one()
    from app.catalog import ALL_CITY_LABELS
    assert list(search.cities) == list(ALL_CITY_LABELS)

    body = signed_in_client.get("/dashboard?tab=scm").get_data(as_text=True)
    assert "Supply chain" in body


def test_scm_board_keeps_a_week(app, signed_in_client, db_session):
    from datetime import datetime, timedelta, timezone

    from app.models import Job, SavedSearch, User
    from app.results import load_db_matches
    from app.sync import rebuild_matches_for_user

    signed_in_client.post("/search", data={
        "ack_lock": "1", "title_slug": "supply-chain-mgmt", "experience_bucket": "3-6",
    })
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    five_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
    job = Job(
        source="test", company="Nucor", title="Supply Chain Analyst",
        normalized_title="supply chain analyst",
        url="https://example.com/jobs/scm-1", city="chicago",
        location="Chicago, IL", description="", vertical="scm",
        is_technical=False, posted_at=five_days_ago,
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id
    rebuild_matches_for_user(user.id)
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "scm"
    ).one()
    matches = load_db_matches(search)
    assert any(m["id"] == job_id for m in matches), "5-day-old SCM job fell off the 7-day board"


def test_run_multi_routes_one_sweep_to_all_tracks(monkeypatch, tmp_path):
    """run_multi fetches boards once and routes each posting to every track
    whose title filter matches (2026-07-20 runtime fix)."""
    import scraper_analyst
    import scraper_project
    import scraper_scm

    calls = {"workday": 0, "greenhouse": 0}

    def fake_workday(name, tenant, ver, site, title_filter=None,
                     vertical=None, source_suffix=None, search_terms=None):
        calls["workday"] += 1
        jobs = []
        for title in ("Supply Chain Analyst", "Project Manager, Ops",
                      "Data Analyst", "Chef de Cuisine"):
            if title_filter(title):
                jobs.append(scraper_scm.make_job(
                    company=name, title=title,
                    url=f"https://x.test/{name}/{title.replace(' ', '-')}",
                    city="chicago", location="Chicago, IL",
                    source=f"workday-{source_suffix}", posted_dt=None,
                    posted_label="", vertical=vertical,
                ))
        return jobs

    monkeypatch.setattr(scraper_scm, "scrape_workday", fake_workday)
    monkeypatch.setattr(scraper_scm, "scrape_greenhouse",
                        lambda *a, **k: calls.__setitem__("greenhouse", calls["greenhouse"] + 1) or [])
    monkeypatch.setattr(scraper_scm, "collect_extra_jobs", lambda **k: [])
    monkeypatch.setattr(scraper_scm, "SCM_WORKDAY_COMPANIES",
                        [("Acme", "acme", 1, "External")])
    monkeypatch.setattr(scraper_scm, "SCM_GREENHOUSE_COMPANIES", [("GH", "gh")])
    monkeypatch.setattr(scraper_scm.time, "sleep", lambda *_: None)

    out = {v: tmp_path / f"{v}.json" for v in ("scm", "project", "analyst")}
    tracks = [
        {"title_filter": scraper_scm.title_is_scm, "vertical": "scm",
         "source_suffix": "scm", "search_terms": scraper_scm.SCM_SEARCH_TERMS,
         "out_file": out["scm"], "label": "SCM"},
        {"title_filter": scraper_project.title_is_project, "vertical": "project",
         "source_suffix": "project",
         "search_terms": scraper_project.PROJECT_SEARCH_TERMS,
         "out_file": out["project"], "label": "Project"},
        {"title_filter": scraper_analyst.title_is_analyst, "vertical": "analyst",
         "source_suffix": "analyst",
         "search_terms": scraper_analyst.ANALYST_SEARCH_TERMS,
         "out_file": out["analyst"], "label": "Analyst"},
    ]
    assert scraper_scm.run_multi(tracks) == 0

    import json as _json
    # ONE Workday board sweep and ONE Greenhouse fetch served all 3 tracks.
    assert calls == {"workday": 1, "greenhouse": 1}
    scm_jobs = _json.loads(out["scm"].read_text())
    project_jobs = _json.loads(out["project"].read_text())
    analyst_jobs = _json.loads(out["analyst"].read_text())
    assert [j["title"] for j in scm_jobs] == ["Supply Chain Analyst"]
    assert [j["title"] for j in project_jobs] == ["Project Manager, Ops"]
    assert [j["title"] for j in analyst_jobs] == ["Data Analyst"]
    assert all(j["vertical"] == "analyst" for j in analyst_jobs)
    assert all(j["source"] == "workday-analyst" for j in analyst_jobs)
