"""Resume-vs-posting fit scoring (app/fit.py)."""
import time

from app.fit import (
    MAX_SCAN_CHARS,
    ResumeProfile,
    build_profile,
    score_fit,
    terms_in,
)


RESUME = """
Divine Doe — Technical Program Manager
Vice President, Technical Program and Product Manager at a large bank.
Led cloud migration of 50+ mission-critical applications to AWS, integrating
LLM-powered APIs. Agile delivery with Jira and Confluence, sprint planning,
backlog refinement, stakeholder engagement, executive communication, risk
register ownership, vendor coordination, and go-live management. Built
executive dashboards in Tableau and Power BI. 10 years of experience.
"""


def test_aliases_resolve_to_one_canonical_skill():
    """A resume says "Technical Program Manager" where a posting says "program
    management" — without aliases a ten-year program manager scored 1 of 10
    against a program manager job."""
    assert "program management" in terms_in("Technical Program Manager")
    assert "program management" in terms_in("program management experience")
    assert "product management" in terms_in("Product Owner for the platform")
    assert "cloud migration" in terms_in("led the cloud modernization effort")
    # Surface forms collapse: one skill, not three.
    assert terms_in("agile, Agile Delivery, AGILE") == {"agile"}


def test_a_matching_posting_scores_higher_than_an_unrelated_one():
    profile = build_profile(RESUME, years=10)
    program = score_fit(
        profile,
        "Senior Technical Program Manager",
        "You will run program management for cloud migration to AWS, driving "
        "agile delivery, sprint planning, stakeholder management and risk "
        "management. 5+ years of experience required. Jira, Confluence.",
    )
    unrelated = score_fit(
        profile,
        "Registered Nurse, Oncology",
        "Provide direct patient care, administer medication, maintain clinical "
        "documentation, and support onboarding of new nursing staff. Requires "
        "an active RN license and 5+ years of bedside experience.",
    )
    assert program["score"] > unrelated["score"]
    assert program["label"] == "Strong fit"
    assert "program management" in program["matched"]
    assert program["summary"].startswith("Matches ")


def test_score_explains_itself():
    """A number the user can't interrogate is worse than no number."""
    profile = build_profile(RESUME, years=10)
    fit = score_fit(
        profile,
        "Program Manager, Payments",
        "Program management for a payments platform. Requires SQL, Kubernetes, "
        "Terraform, agile, and stakeholder management. 8+ years of experience.",
    )
    assert "agile" in fit["matched"]
    # Things the posting asks for that the resume doesn't show are named too.
    assert "kubernetes" in fit["missing"]
    assert "terraform" in fit["missing"]
    assert fit["low_signal"] is False


def test_a_thin_posting_does_not_score_as_a_bad_match():
    """A description the scraper couldn't reach is our problem, not the
    candidate's — the skills weight moves to the signals that still hold."""
    profile = build_profile(RESUME, years=10)
    fit = score_fit(profile, "Technical Program Manager", "")
    assert fit["low_signal"] is True
    assert fit["score"] >= 65
    assert "too little detail" in fit["summary"]


def test_being_far_over_the_requirement_is_not_a_perfect_fit():
    profile = build_profile(RESUME, years=10)
    senior = score_fit(
        profile, "Program Manager",
        "Program management, agile, stakeholder management. 8+ years of experience required.",
    )
    junior = score_fit(
        profile, "Associate Program Manager",
        "Program management, agile, stakeholder management. 1+ years of experience required.",
    )
    assert junior["score"] < senior["score"]


def test_no_resume_means_no_score():
    assert score_fit(None, "Program Manager", "anything") is None
    assert score_fit(ResumeProfile(skills=frozenset(), years=None), "PM", "x") is None


def test_scoring_is_bounded_on_hostile_input():
    """Descriptions are scraped from arbitrary pages and resumes are uploaded;
    neither should be able to make the board render slowly."""
    profile = build_profile("agile " * 50_000, years=10)
    started = time.monotonic()
    fit = score_fit(profile, "Program Manager", "program management " * 50_000)
    assert time.monotonic() - started < 3
    assert 0 <= fit["score"] <= 100
    assert len(profile.text) <= MAX_SCAN_CHARS


def test_board_cards_carry_a_fit_score(signed_in_client, db_session):
    """The dashboard renders the badge for a user who has a base resume."""
    from app.models import BaseResume, Job, JobMatch, SavedSearch, User

    user = db_session.query(User).first()
    db_session.add(BaseResume(
        user_id=user.id, filename="r.pdf", file_path="/tmp/r.pdf",
        content_type="application/pdf", extracted_text=RESUME, years_experience=10,
    ))
    job = Job(
        source="test", company="Acme", title="Senior Technical Program Manager",
        normalized_title="senior technical program manager",
        url="https://example.com/jobs/fit", city="nyc", location="New York, NY",
        description=("Program management for a cloud migration to AWS. Agile "
                     "delivery, sprint planning, stakeholder management, Jira. "
                     "5+ years of experience."),
        vertical="pm", is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    db_session.add(JobMatch(saved_search_id=search.id, user_id=user.id, job_id=job.id))
    db_session.commit()

    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "fit-badge" in body
    assert "Strong fit" in body
    assert "skills this posting names" in body


def test_board_does_not_list_matched_or_missing_keywords(signed_in_client, db_session):
    """Removed at owner request 2026-08-21: the card shows the score and one
    line of reasoning, not the keyword lists. fit.matched / fit.missing are
    still computed — this guard is what keeps them off the board."""
    from app.models import BaseResume, Job, JobMatch, SavedSearch, User

    user = db_session.query(User).first()
    db_session.add(BaseResume(
        user_id=user.id, filename="r.pdf", file_path="/tmp/r.pdf",
        content_type="application/pdf", extracted_text=RESUME, years_experience=10,
    ))
    job = Job(
        source="test", company="Acme", title="Program Manager, Payments",
        normalized_title="program manager, payments",
        url="https://example.com/jobs/no-keywords", city="nyc",
        location="New York, NY",
        description=("Program management for payments. Requires agile, Jira, "
                     "governance, process improvement and Kubernetes. 5+ years "
                     "of experience."),
        vertical="pm", is_technical=True,
    )
    db_session.add(job)
    db_session.commit()
    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    db_session.add(JobMatch(saved_search_id=search.id, user_id=user.id, job_id=job.id))
    db_session.commit()

    body = signed_in_client.get("/dashboard").get_data(as_text=True)
    assert "fit-badge" in body            # the score itself stays
    assert "You have:" not in body
    assert "Not on your resume:" not in body
    assert "kubernetes" not in body.lower()


# --- Off-track vocabulary -------------------------------------------------
#
# The failure these guard against: a posting that names risk management,
# compliance, reporting and governance scores like a strong program-manager
# match even when the actual job is supervising sales-practice misconduct
# across retail brokerage products. Every posting below is a real one the owner
# flagged as "this is not a tech role".

SECURITIES_POSTING = """
High level understanding of FRB, SEC and FINRA regulations, with a focus on
sales practice, misconduct and suitability concerns around retail products in
brokerage and advisory accounts. Working knowledge of Futures, FX, Annuities,
Structured Investments, Alternative Investments, Exchange-Traded Products,
Fixed Income, Equities, Options, Unit Investment Trusts and Mutual Funds.
Partner with stakeholders on risk management, compliance and reporting.
"""

HR_POSTING = """
Background in People Operations, HR transformation, People systems, or
supporting executive-level initiatives and Chief of Staff functions is a strong
plus. Own the roadmap, partner with stakeholders, agile delivery, reporting.
"""

QUANT_POSTING = """
Quantitative background in business, economics, finance, engineering,
mathematics, analytics, or a related discipline. Own the roadmap, work with
stakeholders, agile delivery, sql, reporting, risk management.
"""

CUSTODY_POSTING = """
Experience in wealth management, RIA custody, or advisor technology, or working
with custodial/clearing operations (e.g., First Clearing, Schwab, Fidelity).
Own the roadmap, partner with stakeholders, agile delivery, reporting.
"""

LICENSE_POSTING = """
Series 7, 63 and SIE or ability to obtain. Own the roadmap, partner with
stakeholders, agile delivery, reporting, risk management, jira, dependencies.
"""

CLEAN_POSTING = """
Technical Program Manager: own the roadmap, run agile delivery, manage
stakeholders and dependencies, risk management, reporting, Jira, cloud
migration, API integration, compliance. Benefits include a 401(k) with mutual
funds and company match, payroll deductions, and high fidelity design tooling.
Qualitative and quantitative user research a plus. Contact Human Resources for
accommodation requests.
"""


def test_off_track_postings_sink_below_a_real_match():
    profile = build_profile(RESUME, years=10)
    clean = score_fit(profile, "Technical Program Manager", CLEAN_POSTING, "pm")
    for posting in (SECURITIES_POSTING, HR_POSTING, QUANT_POSTING,
                    CUSTODY_POSTING, LICENSE_POSTING):
        fit = score_fit(profile, "Program Manager", posting, "pm")
        assert fit["off_track"], posting[:60]
        assert fit["score"] < clean["score"], posting[:60]
        # It is a downrank, not a filter — the card still shows a number.
        assert fit["score"] > 0
    assert not clean["off_track"]


def test_off_track_reason_reaches_the_card():
    profile = build_profile(RESUME, years=10)
    fit = score_fit(profile, "Program Manager", SECURITIES_POSTING, "pm")
    assert "Reads as a securities / brokerage role" in fit["summary"]
    assert "finra" in fit["off_track_terms"]


def test_one_decisive_term_is_enough():
    """A Series 7 requirement is the whole signal — waiting for a third
    securities term would let the most decisive postings through untouched."""
    profile = build_profile(RESUME, years=10)
    fit = score_fit(profile, "Program Manager", LICENSE_POSTING, "pm")
    assert fit["off_track"] == ["a securities / brokerage role"]


def test_boilerplate_alone_never_fires():
    """"Mutual funds" is 401(k) boilerplate, "human resources" is the EEO
    paragraph, and "high fidelity" is ordinary product vocabulary. None of them
    may cost a real posting a single point."""
    profile = build_profile(RESUME, years=10)
    assert not score_fit(profile, "Technical Program Manager",
                         CLEAN_POSTING, "pm")["off_track"]


def test_a_vocabulary_is_not_off_track_on_its_own_board():
    """Brokerage language is the point of the finance board, HR language of the
    HR board — the penalty only ever applies to boards the posting is off."""
    profile = build_profile(RESUME, years=10)
    for posting, vertical in ((SECURITIES_POSTING, "finance"),
                              (CUSTODY_POSTING, "finance"),
                              (LICENSE_POSTING, "finance"),
                              (HR_POSTING, "hr"),
                              (QUANT_POSTING, "analyst")):
        on_board = score_fit(profile, "Program Manager", posting, vertical)
        off_board = score_fit(profile, "Program Manager", posting, "pm")
        assert not on_board["off_track"]
        assert on_board["score"] > off_board["score"]


def test_off_track_scan_is_bounded():
    """Same bound as the skills scan: a scraped description can't make the
    board render slowly."""
    profile = build_profile(RESUME, years=10)
    started = time.monotonic()
    score_fit(profile, "Program Manager", SECURITIES_POSTING * 20_000, "pm")
    assert time.monotonic() - started < 2.0


def test_green_starts_at_85():
    """Owner's call 2026-08-22: an 80 was reading as "apply to this" while
    better matches sat below it on the board. Nothing under 85 may come back
    with the green tone."""
    from app.fit import LABELS

    tones = {label: (floor, tone) for floor, label, tone in LABELS}
    assert tones["Strong fit"] == (85, "strong")
    # Everything between the stretch floor and green shares the amber tone in
    # base.html — the only green tone on the board is "strong".
    assert [tone for _, _, tone in LABELS] == ["strong", "good", "possible", "stretch"]


def test_only_the_strong_tone_is_green():
    """The badge palette lives in base.html; this is the guard that keeps
    "Good fit" from drifting back to a blue/green swatch."""
    from pathlib import Path

    css = Path(__file__).resolve().parents[1].joinpath("app/templates/base.html").read_text()
    amber = "#8a6100"
    for tone in ("good", "possible"):
        line = next(l for l in css.splitlines() if f".fit-{tone} " in l)
        assert amber in line, line
    assert "#0a7f3f" in next(l for l in css.splitlines() if ".fit-strong " in l)
