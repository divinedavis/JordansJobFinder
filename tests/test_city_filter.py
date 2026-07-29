"""The dashboard's city filter.

The user ticks the cities they want to see; the choice is stored on the saved
search (not localStorage) so it survives a refresh, a new sign-in and a
different device. Stored as the DESELECTED set, so a metro that starts
producing jobs later shows up instead of being suppressed by an old filter.
"""

CITIES = (("philadelphia-pa", "Philadelphia, PA"), ("dallas-tx", "Dallas, TX"))


def _seed_board(db_session, cities=CITIES):
    from app.models import Job, JobMatch, SavedSearch, User

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id).first()
    for index, (slug, label) in enumerate(cities):
        job = Job(
            source="test", company=f"GE Vernova {index}", title="Program Manager",
            normalized_title="program manager", url=f"https://example.com/jobs/filter-{index}",
            city=slug, location=label, description="", vertical="pm", is_technical=True,
        )
        db_session.add(job)
        db_session.commit()
        db_session.add(JobMatch(user_id=user.id, saved_search_id=search.id, job_id=job.id))
        db_session.commit()


def _board(client):
    return client.get("/dashboard", follow_redirects=True).get_data(as_text=True)


def _saved_search():
    """Re-fetch through a fresh session: each request tears the scoped session
    down, which detaches anything held from before."""
    from app.db import get_db
    from app.models import SavedSearch, User

    db = get_db()
    user = db.query(User).filter(User.email == "user@example.com").one()
    return db, db.query(SavedSearch).filter(SavedSearch.user_id == user.id).first()


def _hidden_cities():
    return _saved_search()[1].hidden_cities


def _apply(client, selected, known=("Philadelphia, PA", "Dallas, TX"), tab="pm"):
    """Submit the filter the way the checkbox form does: every offered option
    as known_city, only the ticked ones as city."""
    return client.post(
        "/dashboard/cities",
        data={"action": "apply", "tab": tab, "known_city": list(known), "city": list(selected)},
        follow_redirects=False,
    )


def test_board_renders_a_checkbox_per_city(signed_in_client, db_session):
    _seed_board(db_session)
    body = _board(signed_in_client)
    assert 'action="/dashboard/cities"' in body
    assert 'name="city" value="Philadelphia, PA" checked' in body
    assert 'name="city" value="Dallas, TX" checked' in body
    assert 'name="known_city" value="Dallas, TX"' in body
    assert "showing 2 of 2" in body


def test_deselecting_a_city_removes_its_section(signed_in_client, db_session):
    _seed_board(db_session)

    assert _apply(signed_in_client, ["Philadelphia, PA"]).status_code == 302

    body = _board(signed_in_client)
    assert 'data-city-section="Dallas, TX"' not in body
    assert 'data-city-section="Philadelphia, PA"' in body
    # Still offered in the filter, unchecked, so it can be brought back.
    assert 'name="city" value="Dallas, TX">' in body
    assert "showing 1 of 2" in body


def test_selection_persists_on_the_saved_search(signed_in_client, db_session):
    """Not a per-device preference — a later visit or another device must see
    the same filter."""
    _seed_board(db_session)
    _apply(signed_in_client, ["Philadelphia, PA"])

    assert _hidden_cities() == ["Dallas, TX"]
    assert 'data-city-section="Dallas, TX"' not in _board(signed_in_client)


def test_reselecting_brings_the_city_back(signed_in_client, db_session):
    _seed_board(db_session)
    _apply(signed_in_client, ["Philadelphia, PA"])
    _apply(signed_in_client, ["Philadelphia, PA", "Dallas, TX"])

    assert _hidden_cities() == []
    assert 'data-city-section="Dallas, TX"' in _board(signed_in_client)


def test_select_all_clears_the_filter(signed_in_client, db_session):
    _seed_board(db_session)
    _apply(signed_in_client, [])
    assert _board(signed_in_client).count("data-city-section=") == 0

    signed_in_client.post("/dashboard/cities", data={"action": "select-all", "tab": "pm"})
    assert _hidden_cities() == []
    assert _board(signed_in_client).count("data-city-section=") == 2


def test_selecting_nothing_explains_the_empty_board(signed_in_client, db_session):
    """An empty board with matches in the DB would otherwise look broken."""
    _seed_board(db_session)
    _apply(signed_in_client, [])

    body = _board(signed_in_client)
    assert "No cities are selected" in body
    assert "No matches exist yet for this saved search." not in body


def test_a_deselected_city_with_no_jobs_today_stays_in_the_filter(signed_in_client, db_session):
    """Otherwise filtering out a quiet market would be irreversible."""
    _seed_board(db_session, cities=CITIES[:1])
    signed_in_client.post(
        "/dashboard/cities",
        data={"action": "apply", "tab": "pm",
              "known_city": ["Philadelphia, PA", "Houston, TX"],
              "city": ["Philadelphia, PA"]},
    )

    body = _board(signed_in_client)
    assert 'name="city" value="Houston, TX">' in body
    assert "showing 1 of 2" in body


def test_a_city_that_was_never_offered_is_untouched(signed_in_client, db_session):
    """Only options the page presented can be deselected — a form that omits a
    city must not silently filter it out."""
    _seed_board(db_session)
    signed_in_client.post(
        "/dashboard/cities",
        data={"action": "apply", "tab": "pm",
              "known_city": ["Philadelphia, PA"], "city": ["Philadelphia, PA"]},
    )

    assert _hidden_cities() == []
    assert 'data-city-section="Dallas, TX"' in _board(signed_in_client)


def test_blank_and_overlong_labels_are_cleaned(signed_in_client, db_session):
    """The stored list is a display filter, not a scratch pad."""
    _seed_board(db_session)
    signed_in_client.post(
        "/dashboard/cities",
        data={"action": "apply", "tab": "pm",
              "known_city": ["  ", "X" * 500, "Dallas, TX"], "city": []},
    )

    hidden = _hidden_cities()
    assert "Dallas, TX" in hidden
    assert all(label.strip() and len(label) <= 128 for label in hidden)


def test_filter_defaults_to_everything_for_pre_existing_searches(signed_in_client, db_session):
    """Searches created before the column exists read back NULL — the board
    must render, not blow up."""
    _seed_board(db_session)
    db, search = _saved_search()
    search.hidden_cities = None
    db.commit()

    body = _board(signed_in_client)
    assert 'data-city-section="Dallas, TX"' in body
    assert "showing 2 of 2" in body


def _filter_tag(body):
    start = body.index('<details class="city-filter"')
    return body[start:body.index(">", start) + 1]


def test_filter_starts_collapsed_when_all_cities_are_selected(signed_in_client, db_session):
    _seed_board(db_session)
    assert " open" not in _filter_tag(_board(signed_in_client))


def test_filter_stays_collapsed_after_narrowing_the_board(signed_in_client, db_session):
    """The regression this guards: the filter used to open whenever any city
    was deselected, so a narrowed board covered its own jobs on every load."""
    _seed_board(db_session)
    _apply(signed_in_client, ["Philadelphia, PA"])

    body = _board(signed_in_client)
    assert " open" not in _filter_tag(body)
    # Collapsed, but the summary still reports the selection.
    assert "showing 1 of 2" in body


def test_filter_opens_only_when_nothing_is_selected(signed_in_client, db_session):
    """A zero-city board is empty and this filter is the only way out of it."""
    _seed_board(db_session)
    _apply(signed_in_client, [])

    assert " open" in _filter_tag(_board(signed_in_client))


def test_filtering_requires_sign_in(client):
    response = client.post("/dashboard/cities", data={"action": "apply", "city": "Dallas, TX"})
    assert response.status_code == 302
    assert "/sign-in" in response.headers["Location"]
