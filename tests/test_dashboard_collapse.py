"""Collapsible city sections on the dashboard, and their remembered state.

Collapsing is native <details>/<summary> so it works with JS off; collapse.js
only persists which sections were closed.
"""
import re


def _board(signed_in_client):
    return signed_in_client.get("/dashboard", follow_redirects=True).get_data(as_text=True)


def test_city_sections_are_details_elements(signed_in_client, db_session):
    from app.models import Job, JobMatch, SavedSearch, User

    user = db_session.query(User).filter(User.email == "user@example.com").one()
    search = db_session.query(SavedSearch).filter(SavedSearch.user_id == user.id).first()
    job = Job(
        source="test", company="GE Vernova", title="Program Manager",
        normalized_title="program manager", url="https://example.com/jobs/collapse-1",
        city="philadelphia-pa", location="Philadelphia, PA", description="",
        vertical="pm", is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.add(JobMatch(user_id=user.id, saved_search_id=search.id, job_id=job.id))
    db_session.commit()

    body = _board(signed_in_client)
    assert '<details class="match-section"' in body
    assert 'data-city-section="Philadelphia, PA"' in body
    assert "<summary class=\"match-header\"" in body
    # Sections start expanded; the script closes the remembered ones.
    assert re.search(r'<details class="match-section"[^>]*\sopen>', body)
    assert "</details>" in body


def test_collapse_script_is_loaded_and_scoped_to_the_tab(signed_in_client):
    body = _board(signed_in_client)
    assert "js/collapse.js" in body
    # The script keys stored state by board tab, which it reads from here.
    assert 'data-board-tab=' in body


def test_collapse_script_persists_across_sessions():
    """Regression: the whole point is remembering. A sessionStorage swap (or
    dropping persistence entirely) would still 'work' interactively."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parent.parent
          / "app" / "static" / "js" / "collapse.js").read_text()
    assert "localStorage" in js, "must survive closing the browser"
    assert "sessionStorage" not in js
    assert "toggle" in js, "state is saved on the details toggle event"
    # A storage failure must not break the board (Safari private mode throws).
    assert js.count("try {") >= 2


def test_summary_marker_is_replaced_not_left_default():
    """The native disclosure triangle would sit next to the city name and
    clash with the type; the header uses its own chevron."""
    import pathlib

    css = (pathlib.Path(__file__).resolve().parent.parent
           / "app" / "templates" / "base.html").read_text()
    assert "summary.match-header::-webkit-details-marker" in css
    assert "match-chevron" in css
    assert "prefers-reduced-motion" in css
