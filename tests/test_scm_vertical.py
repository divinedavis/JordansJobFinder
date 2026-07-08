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


def test_scm_scraper_infers_sc_metros_only():
    from scraper_scm import infer_city

    assert infer_city("Charleston, SC") == "charleston-sc"
    assert infer_city("North Charleston, SC") == "charleston-sc"
    assert infer_city("Columbia, SC") == "columbia-sc"
    assert infer_city("Greenville, SC") == "greenville-sc"
    assert infer_city("Spartanburg, SC") == "greenville-sc"
    assert infer_city("Rock Hill, SC") == "rock-hill-sc"
    assert infer_city("Fort Mill, SC") == "rock-hill-sc"
    # Out of scope -> dropped.
    assert infer_city("Charlotte, NC") == ""
    assert infer_city("Atlanta, GA") == ""


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


def test_scm_default_cities_are_sc_metros():
    from app.catalog import SCM_DEFAULT_CITIES

    assert SCM_DEFAULT_CITIES == [
        "Charleston, SC", "Columbia, SC", "Greenville, SC", "Rock Hill, SC",
    ]


def test_selecting_scm_adds_track_capped_to_free_limit(signed_in_client, db_session):
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
    # Free plan caps to 3 of the 4 SC metros.
    assert search.cities == ["Charleston, SC", "Columbia, SC", "Greenville, SC"]

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
        url="https://example.com/jobs/scm-1", city="greenville-sc",
        location="Greenville, SC", description="", vertical="scm",
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
