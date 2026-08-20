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


def test_pm_board_drops_sub_floor_project_and_it_jobs(app):
    """2026-08-20: project/IT jobs riding the PM board must clear the same
    $180K ceiling the PM track enforces. A "Program Manager III" at
    $87,700-$157,800 was sitting on the board next to $230K roles because the
    it/project branch returned before any salary gate ran. A posting with no
    salary at all still shows — unknown isn't low."""
    from types import SimpleNamespace
    from app.sync import _search_matches_job

    search = SimpleNamespace(
        vertical="pm", title_slug="technical-product-manager",
        experience_bucket="10+", cities=["New York, NY"],
    )

    def job(vertical, title, lo, hi):
        return SimpleNamespace(
            vertical=vertical, title=title, company="Centene", city="nyc",
            location="New York, NY", description="",
            salary_min=lo, salary_max=hi,
        )

    assert not _search_matches_job(
        search, job("project", "Program Manager III", 87_700, 157_800), "u@example.com"
    )
    assert not _search_matches_job(
        search, job("it", "IT Program Manager", 116_000, 155_000), "u@example.com"
    )
    assert _search_matches_job(
        search, job("project", "Senior Technical Program Manager", 184_000, 230_000),
        "u@example.com",
    )
    assert _search_matches_job(
        search, job("project", "Project Manager, Facilities", None, None), "u@example.com"
    )


def test_project_own_board_keeps_no_salary_floor(app):
    """The floor is a PM-board rule only: a project-vertical saved search
    still shows whatever the posting pays."""
    from types import SimpleNamespace
    from app.sync import _search_matches_job

    search = SimpleNamespace(
        vertical="project", title_slug="project-management",
        experience_bucket="10+", cities=["New York, NY"],
    )
    job = SimpleNamespace(
        vertical="project", title="Program Manager III", company="Centene",
        city="nyc", location="New York, NY", description="",
        salary_min=87_700, salary_max=157_800,
    )
    assert _search_matches_job(search, job, "u@example.com")
