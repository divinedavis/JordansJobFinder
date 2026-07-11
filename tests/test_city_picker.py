"""State-first city picker (any US city over 50k) and the one-title-per-user
rule (admin exempt)."""


# ── Dataset + validation ──────────────────────────────────────────────────────


def test_city_dataset_loads_and_is_reasonably_sized():
    from app.uscities import cities_by_state, state_choices, valid_city_labels

    assert len(valid_city_labels()) >= 700
    assert 40 <= len(cities_by_state()) <= 51
    # Spot checks incl. the census-name cleanups.
    for label in ("Boise, ID", "Honolulu, HI", "Ventura, CA",
                  "Lancaster, PA", "New York, NY", "Houston, TX"):
        assert label in valid_city_labels(), label
    names = dict(state_choices())
    assert names["ID"] == "Idaho"


def test_cities_are_ordered_by_population_descending():
    # Each state's city list is pre-sorted most-populous first so the dropdown
    # surfaces the biggest cities at the top (the template renders in list
    # order). Spot-check the largest city in a few states.
    from app.uscities import cities_by_state

    data = cities_by_state()
    assert data["NY"][0] == "New York"
    assert data["TX"][0] == "Houston"
    assert data["CA"][0] == "Los Angeles"
    assert data["FL"][0] == "Jacksonville"
    # New York must come before smaller NY cities like Buffalo/Yonkers.
    ny = data["NY"]
    assert ny.index("New York") < ny.index("Buffalo") < ny.index("Yonkers")


def test_valid_city_accepts_any_50k_city_and_legacy_labels(app):
    from app.searches import valid_city

    assert valid_city("Boise, ID")
    assert valid_city("Chattanooga, TN")
    assert valid_city("Florida (other)")   # legacy vertical label
    assert not valid_city("Atlantis, ZZ")
    assert not valid_city("Smallville, KS")


# ── Location matching for non-metro cities ────────────────────────────────────


def test_location_matches_city_requires_city_and_state():
    from app.matching import location_matches_city

    assert location_matches_city("Boise, ID", "Boise, ID")
    assert location_matches_city("USA - Boise, Idaho", "Boise, ID")
    assert location_matches_city("Remote - Boise ID office", "Boise, ID")
    # City name in another state must NOT match.
    assert not location_matches_city("Springfield, MA", "Springfield, IL")
    assert not location_matches_city("Portland, ME", "Portland, OR")
    assert not location_matches_city("", "Boise, ID")


def test_search_matches_job_in_custom_city(signed_in_client, db_session):
    from app.models import Job, JobMatch, SavedSearch, User
    from app.sync import rebuild_matches_for_user

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    search.cities = ["Boise, ID", "Chattanooga, TN", "New York, NY"]
    db_session.commit()

    boise = Job(
        source="test", company="Micron", title="Senior Program Manager",
        normalized_title="senior program manager",
        url="https://example.com/jobs/cc-1", city="extra",
        location="Boise, ID", description="Requires 8+ years of experience.",
        vertical="pm", is_technical=True,
    )
    denver = Job(
        source="test", company="Acme", title="Senior Program Manager",
        normalized_title="senior program manager",
        url="https://example.com/jobs/cc-2", city="extra",
        location="Denver, CO", description="Requires 8+ years of experience.",
        vertical="pm", is_technical=True,
    )
    db_session.add_all([boise, denver])
    db_session.commit()

    rebuild_matches_for_user(user.id)
    db_session.expire_all()
    matched = {
        m.job_id
        for m in db_session.query(JobMatch).filter(JobMatch.user_id == user.id).all()
    }
    assert boise.id in matched
    assert denver.id not in matched


# ── Picker UI + save flow ─────────────────────────────────────────────────────


def test_search_page_renders_state_first_picker(signed_in_client):
    body = signed_in_client.get("/search").get_data(as_text=True)
    assert "data-city-pair" in body
    assert 'data-role="state"' in body
    assert "citypicker.js" in body
    assert 'data-state="ID"' in body  # optgroups carry the state for the JS


def test_saving_three_custom_cities(signed_in_client, db_session):
    from app.models import SavedSearch, User

    resp = signed_in_client.post("/search", data={"ack_lock": "1", 
        "title_slug": "technical-product-manager",
        "experience_bucket": "7-9",
        "city_1": "Boise, ID",
        "city_2": "Chattanooga, TN",
        "city_3": "Madison, WI",
    })
    assert resp.status_code == 302

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    assert search.cities == ["Boise, ID", "Chattanooga, TN", "Madison, WI"]


# ── One title per account (admin exempt) ──────────────────────────────────────


def test_signup_seeds_a_single_track(client, db_session):
    from app.models import SavedSearch, User

    client.post("/sign-in", data={
        "email": "solo@example.com", "password": "Str0ng-Pass-9x",
        "confirm_password": "Str0ng-Pass-9x",
    })
    user = db_session.query(User).filter(User.email == "solo@example.com").one()
    searches = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id
    ).all()
    assert len(searches) == 1
    assert searches[0].vertical == "pm"


def test_choosing_new_title_replaces_track_for_regular_user(signed_in_client, db_session):
    from app.models import SavedSearch, User

    signed_in_client.post("/search", data={"ack_lock": "1", 
        "title_slug": "hr-coordinator", "experience_bucket": "7-9",
    })
    user = db_session.query(User).filter(User.email == "user@example.com").one()
    verticals = [
        s.vertical
        for s in db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id)
    ]
    assert verticals == ["hr"], "regular users hold exactly one track"


def test_admin_is_also_limited_to_one_track(client, db_session):
    """Everyone shows one job selection at a time — the admin included."""
    from app.models import SavedSearch, User

    # conftest sets SUPERUSER_EMAIL=superuser@example.com — the admin account.
    client.post("/sign-in", data={
        "email": "superuser@example.com", "password": "Str0ng-Pass-9x",
        "confirm_password": "Str0ng-Pass-9x",
    })
    client.post("/search", data={"ack_lock": "1", 
        "title_slug": "hr-coordinator", "experience_bucket": "7-9",
    })
    user = db_session.query(User).filter(User.email == "superuser@example.com").one()
    verticals = [
        s.vertical
        for s in db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id)
    ]
    assert verticals == ["hr"]


def test_title_choices_are_combined_one_per_track():
    """Similar titles are merged: the picker offers exactly one option per
    track (no four finance flavors), while legacy sub-track slugs stay valid."""
    from app.catalog import title_choices
    from app.searches import valid_title_slug

    options = title_choices()
    # IT project/program rides the PM option (combined); SCM is its own option.
    assert [o["vertical"] for o in options] == ["pm", "finance", "sales", "hr", "scm"]
    assert len(options) == 5
    # Legacy sub-track slugs must remain valid for existing saved searches.
    assert valid_title_slug("entry-finance-fpa")
    assert valid_title_slug("entry-sales-sdr-bdr")
    assert valid_title_slug("technical-program-manager")
    assert valid_title_slug("it-project-program-manager")
