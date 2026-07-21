"""HR coordinator/generalist vertical: title heuristic, no-salary matching,
PA city coverage (York/Lancaster/Philadelphia/Harrisburg), and the
select-a-track flow on /search that adds the HR tab."""


# ── Title heuristic ───────────────────────────────────────────────────────────


def test_title_is_hr_accepts_coordinator_and_level_above():
    from app.matching import title_is_hr

    for title in (
        "HR Coordinator",
        "Senior HR Coordinator",
        "Human Resources Coordinator",
        "HR Generalist",
        "Senior Human Resources Generalist",
        "HR Specialist",
        "People Operations Coordinator",
    ):
        assert title_is_hr(title), title


def test_title_is_hr_rejects_out_of_scope_titles():
    from app.matching import title_is_hr

    for title in (
        "HR Director",
        "VP, Human Resources",
        "Head of People",
        "HR Intern",
        "Recruiting Coordinator",   # recruiting, not HR core
        "Payroll Analyst",
        "HR Business Partner",      # above the generalist band
    ):
        assert not title_is_hr(title), title


def test_hr_vertical_matches_without_salary(app):
    from app.matching import match_job_for_user

    # No salary on the posting — must still match.
    assert match_job_for_user(
        "hr-coordinator", "7-9", "HR Coordinator", "", None, None, "someone@example.com",
    )
    # A stated low salary must not exclude either.
    assert match_job_for_user(
        "hr-coordinator", "7-9", "HR Generalist", "", 45000, 55000, "someone@example.com",
    )
    # A junior requirement suits a 5+ years candidate — must not filter.
    assert match_job_for_user(
        "hr-coordinator", "7-9", "HR Coordinator", "Requires 2+ years of experience.",
        None, None, "someone@example.com",
    )


# ── City coverage ─────────────────────────────────────────────────────────────


def test_hr_scraper_covers_pa_metros_first():
    from scraper_hr import infer_city

    assert infer_city("York, PA") == "york-pa"
    assert infer_city("Lancaster, PA") == "lancaster-pa"
    assert infer_city("Philadelphia, PA") == "philadelphia-pa"
    assert infer_city("Boston, MA") == "boston"
    assert infer_city("Seattle, WA") == "seattle"
    assert infer_city("Denver, CO") == "denver"
    assert infer_city("Harrisburg, PA") == "harrisburg-pa"
    assert infer_city("Hershey, PA") == "harrisburg-pa"
    # Nationwide since 2026-07-19; out-of-scope towns still drop.
    assert infer_city("New York, NY") == "nyc"
    assert infer_city("Boise, ID") == ""


def test_hr_covers_every_metro():
    """HR used to be pinned to the four PA metros (its original audience), then
    to a PA-first nationwide list. Every track covers every metro since
    2026-07-21 — but PA must still be IN the set, which is what broke when the
    free-tier cap sliced the first 3 off a 29-metro list."""
    from app.catalog import ALL_CITY_LABELS, HR_DEFAULT_CITIES

    assert list(HR_DEFAULT_CITIES) == list(ALL_CITY_LABELS)
    for pa in ("York, PA", "Lancaster, PA", "Harrisburg, PA"):
        assert pa in HR_DEFAULT_CITIES

def test_selecting_hr_title_adds_hr_tab_with_every_metro(signed_in_client, db_session):
    from app.catalog import ALL_CITY_LABELS
    from app.models import SavedSearch, User

    signed_in_client.post("/search", data={
        "ack_lock": "1", "title_slug": "hr-coordinator", "experience_bucket": "3-6",
    })
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "hr"
    ).one()
    assert list(search.cities) == list(ALL_CITY_LABELS)
    assert "York, PA" in search.cities

def test_hr_search_matches_hr_jobs_in_pa(signed_in_client, db_session):
    from app.models import Job, JobMatch, User
    from app.sync import rebuild_matches_for_user

    signed_in_client.post("/search", data={"ack_lock": "1", 
        "title_slug": "hr-coordinator", "experience_bucket": "7-9",
    })
    user = db_session.query(User).filter(User.email == "user@example.com").one()

    good = Job(
        source="test", company="WellSpan Health", title="Senior HR Coordinator",
        normalized_title="senior hr coordinator",
        url="https://example.com/jobs/hr-1", city="york-pa",
        location="York, PA", description="", vertical="hr", is_technical=False,
    )
    director = Job(
        source="test", company="Hershey", title="HR Director",
        normalized_title="hr director",
        url="https://example.com/jobs/hr-2", city="harrisburg-pa",
        location="Harrisburg, PA", description="", vertical="hr", is_technical=False,
    )
    db_session.add_all([good, director])
    db_session.commit()

    rebuild_matches_for_user(user.id)
    db_session.expire_all()
    matched = {
        m.job_id
        for m in db_session.query(JobMatch).filter(JobMatch.user_id == user.id).all()
    }
    assert good.id in matched
    assert director.id not in matched


def test_dashboard_has_no_hardcoded_track_switch_pill(signed_in_client):
    """The tab row exposes a single 'Edit search' link — the only way to change
    tracks — with no track-specific 'Switch to ...' pill singling out HR."""
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    # Edit search moved to the Profile hub; the dashboard tab row has neither
    # an inline edit link nor a track-specific "Switch to ..." pill.
    assert "Switch to" not in body

    # Switching to HR still works via the search form (the Edit search path).
    signed_in_client.post("/search", data={"ack_lock": "1", 
        "title_slug": "hr-coordinator", "experience_bucket": "7-9",
    })
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "?tab=hr" in body


def test_hr_scraper_infers_nationwide_metros():
    """2026-07-19: HR expanded beyond the PA metros."""
    from scraper_hr import infer_city

    assert infer_city("Chicago, IL") == "chicago"
    assert infer_city("Phoenix, AZ") == "phoenix"
    # San Antonio was dropped on 2026-07-21 (outside the top 20).
    assert infer_city("San Antonio, TX") == ""
    assert infer_city("Glendale, AZ") == "phoenix"
    assert infer_city("Philadelphia, PA") == "philadelphia-pa"
    assert infer_city("Houston, TX") == "houston"
