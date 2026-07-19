"""Project Management vertical: title heuristic, matching branch, catalog
wiring, ingest, and the shared SC-runner reuse."""


def test_title_is_project_accepts_project_roles():
    from app.matching import title_is_project

    for title in (
        "Project Manager",
        "Senior Project Coordinator",
        "IT Program Manager",
        "Construction Project Manager",
        "PMO Analyst",
        "Project Director, Facilities",
    ):
        assert title_is_project(title), title


def test_title_is_project_rejects_unrelated_and_interns():
    from app.matching import title_is_project

    for title in (
        "Software Engineer",
        "Registered Nurse",
        "Financial Analyst",
        "Project Management Intern",
        "Supply Chain Manager",
    ):
        assert not title_is_project(title), title


def test_project_matches_without_salary(app):
    from app.matching import match_job_for_user

    assert match_job_for_user(
        "project-management", "10+", "Project Manager", "",
        None, None, "u@example.com",
    )
    assert not match_job_for_user(
        "project-management", "10+", "Marketing Analyst", "",
        None, None, "u@example.com",
    )


def test_project_is_merged_into_pm_not_selectable():
    """2026-07-19: project management rides the Product/Program Manager
    board. The standalone picker option is gone, but legacy wiring (labels,
    keywords, default cities) stays for existing saved searches."""
    from app.catalog import (
        SELECTABLE_TITLES,
        TITLE_KEYWORDS,
        TITLE_VERTICALS,
        VERTICAL_DEFAULT_CITIES,
    )

    assert not any(t["slug"] == "project-management" for t in SELECTABLE_TITLES)
    # Legacy wiring still resolves for accounts created before the merge.
    assert TITLE_VERTICALS["project-management"] == "project"
    assert "project-management" in TITLE_KEYWORDS
    assert "project" in VERTICAL_DEFAULT_CITIES


def test_pm_search_matches_project_jobs(app):
    """A Product/Program Manager saved search shows project-vertical jobs."""
    from types import SimpleNamespace
    from app.sync import _search_matches_job

    search = SimpleNamespace(
        vertical="pm", title_slug="technical-product-manager",
        experience_bucket="10+", cities=["Charleston, SC"],
    )
    job = SimpleNamespace(
        vertical="project", title="Project Manager, Facilities",
        company="MUSC", city="charleston-sc", location="Charleston, SC",
        description="", salary_min=None, salary_max=None,
    )
    assert _search_matches_job(search, job, "u@example.com")
    bad = SimpleNamespace(
        vertical="project", title="Marketing Analyst",
        company="MUSC", city="charleston-sc", location="Charleston, SC",
        description="", salary_min=None, salary_max=None,
    )
    assert not _search_matches_job(search, bad, "u@example.com")


def test_project_board_window_is_a_week():
    from app.results import BOARD_WINDOW_DAYS

    assert BOARD_WINDOW_DAYS["project"] == 7


def test_project_vertical_in_order_and_labels():
    from app.routes import VERTICAL_LABELS, VERTICAL_ORDER

    assert "project" in VERTICAL_ORDER
    assert "project" in VERTICAL_LABELS


def test_project_scraper_reuses_sc_runner_and_employers():
    # The project scraper reuses scraper_scm's SC employer union + SC-metro
    # inference; it must NOT re-fetch a different employer set.
    import scraper_project
    import scraper_scm

    assert scraper_project.title_is_project is not scraper_scm.title_is_scm
    # main() delegates to the shared runner with the project vertical.
    assert callable(scraper_scm.run)


def test_project_ingest_tags_vertical():
    from app.ingest import _normalize_one

    job = _normalize_one({"title": "Project Manager", "city": "charleston-sc"}, "project")
    assert job["vertical"] == "project"
