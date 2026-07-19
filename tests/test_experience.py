"""Resume years-of-experience estimation + resume-derived matching."""
from datetime import date

from app.experience import bucket_for_years, estimate_resume_years


# ── Parser ────────────────────────────────────────────────────────────────

def test_no_text_returns_none():
    assert estimate_resume_years(None) is None
    assert estimate_resume_years("") is None
    assert estimate_resume_years("Product manager with strong agile skills.") is None


def test_single_month_year_range():
    text = "Acme Corp — Product Manager\nJan 2018 – Jan 2021\nDid things."
    assert estimate_resume_years(text) == 3


def test_present_range_counts_to_today():
    start_year = date.today().year - 4
    text = f"Globex — PM\nMarch {start_year} – Present"
    assert estimate_resume_years(text) in (4, 5)  # depends on current month


def test_overlapping_roles_count_once():
    # Concurrent roles (or education overlapping a job) must not double-count.
    text = (
        "Initech — Senior PM\nJan 2015 – Dec 2020\n"
        "Side Consulting — Advisor\nJan 2018 – Dec 2020\n"
    )
    assert estimate_resume_years(text) == 6


def test_disjoint_roles_sum():
    text = (
        "Job A\nJan 2010 – Dec 2012\n"
        "Job B\nJan 2015 – Dec 2019\n"
    )
    assert estimate_resume_years(text) == 8


def test_numeric_month_format():
    text = "Hooli — APM\n03/2019 – 09/2022"
    assert estimate_resume_years(text) == 4  # 42 months rounds to 4


def test_bare_year_range():
    text = "Vandelay Industries\n2014 – 2017\nSales."
    assert estimate_resume_years(text) == 4  # Jan 2014 – Dec 2017 inclusive


def test_garbage_ranges_ignored():
    # Reversed, ancient, and future-start ranges must be dropped.
    text = "Weird 2020 – 2015\nOld 1902 – 1950\nFuture 2093 – 2099"
    assert estimate_resume_years(text) is None


def test_month_names_full_and_abbreviated():
    text = "September 2016 — Aug. 2019"
    assert estimate_resume_years(text) == 3


def test_bucket_for_years():
    assert bucket_for_years(None) is None
    assert bucket_for_years(0) == "0-2"
    assert bucket_for_years(2) == "0-2"
    assert bucket_for_years(3) == "3-6"
    assert bucket_for_years(6) == "3-6"
    assert bucket_for_years(7) == "7-9"
    assert bucket_for_years(9) == "7-9"
    assert bucket_for_years(10) == "10+"
    assert bucket_for_years(25) == "10+"


# ── Resume-derived matching ───────────────────────────────────────────────

def _add_resume(db, user_id, years):
    from app.models import BaseResume

    db.add(
        BaseResume(
            user_id=user_id,
            filename="resume.pdf",
            file_path="/tmp/resume.pdf",
            content_type="application/pdf",
            extracted_text="stub",
            years_experience=years,
        )
    )
    db.commit()


def _user_and_search(db, email="user@example.com"):
    from app.models import SavedSearch, User

    user = db.query(User).filter(User.email == email).one()
    search = db.query(SavedSearch).filter(SavedSearch.user_id == user.id).first()
    return user, search


SENIOR_JOB = dict(
    title="Senior Product Manager",
    description=(
        "Requires 8+ years of experience. Salary $200,000 - $240,000. "
        "Agile, cloud, API, roadmap, stakeholders."
    ),
)


def test_resume_bucket_overrides_saved_bucket(signed_in_client, db_session):
    """A user whose saved search says 0-2 but whose resume shows 8 years must
    match senior jobs (resume wins)."""
    from app.sync import _search_matches_job, _resume_buckets_by_user

    user, search = _user_and_search(db_session)
    assert search is not None
    search.experience_bucket = "0-2"
    db_session.commit()
    _add_resume(db_session, user.id, 8)

    buckets = _resume_buckets_by_user(db_session)
    assert buckets[user.id] == "7-9"

    from app.matching import match_job_for_user

    # With the resume band (7-9), an 8+ years senior job matches.
    assert match_job_for_user(
        search.title_slug, buckets[user.id],
        SENIOR_JOB["title"], SENIOR_JOB["description"],
        200000, 240000, user.email,
        resume_bucket=buckets[user.id],
    )
    # A genuinely junior resume (0-2 band) must NOT be shown an 8+ years job,
    # even on the PM track's open scope.
    assert not match_job_for_user(
        search.title_slug, "0-2",
        SENIOR_JOB["title"], SENIOR_JOB["description"],
        200000, 240000, user.email,
        resume_bucket="0-2",
    )
    # No resume at all keeps the PM open-scope behavior (5+ years rule).
    assert match_job_for_user(
        search.title_slug, search.experience_bucket,
        SENIOR_JOB["title"], SENIOR_JOB["description"],
        200000, 240000, user.email,
    )


def test_no_resume_falls_back_to_saved_bucket(signed_in_client, db_session):
    from app.experience import effective_experience_bucket

    user, search = _user_and_search(db_session)
    search.experience_bucket = "3-6"
    db_session.commit()
    assert effective_experience_bucket(db_session, search) == "3-6"

    _add_resume(db_session, user.id, 12)
    assert effective_experience_bucket(db_session, search) == "10+"


def test_unparseable_resume_falls_back(signed_in_client, db_session):
    user, search = _user_and_search(db_session)
    search.experience_bucket = "7-9"
    db_session.commit()
    _add_resume(db_session, user.id, None)

    from app.experience import effective_experience_bucket
    from app.sync import _resume_buckets_by_user

    assert effective_experience_bucket(db_session, search) == "7-9"
    assert user.id not in _resume_buckets_by_user(db_session)


# ── Dashboard banner ──────────────────────────────────────────────────────

def test_dashboard_banner_with_resume_years(signed_in_client, db_session):
    user, _ = _user_and_search(db_session)
    _add_resume(db_session, user.id, 8)
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "Matched to your experience" in body
    assert "8 years of experience" in body
    assert "these are the jobs for you" in body


def test_dashboard_prompts_upload_without_resume(signed_in_client):
    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "Upload your resume" in body
    assert "match jobs to your level automatically" in body


def test_search_form_hides_picker_with_resume(signed_in_client, db_session):
    user, _ = _user_and_search(db_session)
    _add_resume(db_session, user.id, 5)
    body = signed_in_client.get("/search").get_data(as_text=True)
    assert "Detected from your resume" in body
    assert 'name="experience_bucket"' not in body


def test_search_form_shows_picker_without_resume(signed_in_client):
    body = signed_in_client.get("/search").get_data(as_text=True)
    assert 'name="experience_bucket"' in body
