"""The two New York cards on the owner's board on 2026-08-22.

Pfizer "Senior Product Manager, Data Products" and Citigroup "Securities
Finance Product Manager, Vice President" both landed at 95% Strong fit, both
were applied to, and both sat in the same New York, NY group. Three things
about that pair are worth holding still:

1. The Citigroup posting is a *securities* posting that must NOT be downranked.
   OFF_TRACK_VOCABULARIES["securities"] exists to sink retail-brokerage
   supervision roles that only look like program management, and it is exempt
   only on the finance board — this card is on the pm board, names securities
   financing, broker-dealers and capital markets throughout, and is still a
   real product-management job. It is the closest thing to a false positive the
   downrank has, so it is the case that proves the rule is written narrowly.

2. Both postings state their requirement differently — Pfizer says "6+ years",
   Citi says "6-10 years" — and the board read them as 6 and 10. A range has to
   resolve to its top, or a 10-year candidate reads as overqualified.

3. Applied cards stay on the board for BOARD_GRACE_HOURS and say how long they
   have left. Both cards showed that countdown at once.

Descriptions below are the scraped text of the real postings, trimmed to the
paragraphs that carry the requirements and the vocabulary the scorer reads.
"""

from datetime import datetime, timedelta, timezone


# A 10-year technical program/product manager. Deliberately NOT the owner's
# real resume: this file is public and the fit numbers only need a profile of
# the same shape.
RESUME = """
Vice President, Technical Program and Product Manager - capital markets and
digital platform modernization.
Ten years in financial services product management. Own product strategy and
the roadmap end to end, translating business and regulatory requirements into
epics, user stories and acceptance criteria. Product owner on agile delivery
teams, running backlog refinement, sprint planning and release readiness in
Jira and Confluence. Led AWS cloud migration of 50+ mission-critical
applications, owning integration architecture, API development and the system
dependencies between them. Built AI/LLM integrations and machine learning
solutions, including an AI customer service agent, and drove workflow
automation across support and documentation. Ran change management and process
improvement for the platform infrastructure rollout. SQL, data analytics, KPI
tracking, executive dashboards in Tableau and Power BI. Salesforce, CRM and
Smartsheet. Stakeholder engagement and executive communication across global
teams. 10 years of experience.
"""

PFIZER_DESCRIPTION = """
This role will lead expansion of Pfizer's commercial data products globally
while enabling AI-powered marketing workflows that drive intelligent,
personalized experiences for HCPs and patients across markets. Drive product
strategy and execution for global expansion of data products across
international markets. Partner with regional and market teams to identify local
requirements, prioritize use cases, and drive successful adoption of enterprise
platforms and workflows. Define and scale AI-enabled marketing workflows
supporting audience creation, segmentation, and activation across CRM and Media
channels. Manage trade-offs between global platform standardization and
market-specific customization, ensuring solutions remain scalable, reusable,
and maintainable. Partner with Engineering, Data Science, and Data Architecture
teams to define product requirements, workflow specifications, APIs, decision
logic, and integration patterns. Drive adoption of AI-powered capabilities and
automation across markets. Lead global rollout planning, stakeholder alignment,
launch readiness, and continuous optimization across regions. Here Is What You
Need (Minimum Requirements) Bachelor's degree with at least 6+ years of
experience; OR a Master's degree with more than 5+ years of experience; OR a
Ph.D. with 1+ years of experience. Product management experience, with focus on
enterprise data, ad tech, marketing technology, using AI/ML workflows.
Demonstrated experience working with or supporting international markets and
global product rollouts. Strong technical aptitude with the ability to
understand data models, APIs, workflow orchestration, integration
architectures, system dependencies, and architectural trade-offs. Experience
defining detailed product requirements, workflow specifications, business
rules, and acceptance criteria in spec-driven development environments.
Excellent written and verbal communication skills. Familiarity with cloud and
data ecosystems such as Salesforce Data Cloud, Snowflake, AWS, and related
activation platforms.
"""

CITI_DESCRIPTION = """
Citi's Securities Financing business sits at the heart of its market-leading
Services division - a global franchise trusted by the world's largest
institutional investors, broker-dealers, and asset managers. We are rebuilding
our lending platform from the ground up - engineering a best-in-class,
next-generation infrastructure designed to power our global business and
support ambitious product expansion plans across markets. Responsibilities Lead
the product strategy and roadmap for Securities Finance digital products,
owning the full lifecycle from ideation through to client adoption and
continuous improvement. Translating those requirements into clear capabilities,
epics and stories for our technology partners. Act as Product Owner within
Agile delivery teams, defining and prioritizing the product backlog and
directing technology efforts to ensure on-time, high-quality delivery.
Translate complex business needs into detailed requirements, user stories, and
acceptance criteria across multiple concurrent workstreams. Apply data and
performance analytics to drive product decisions, identify revenue
optimization opportunities, and reduce operational and financial risk. Lead
Target Operating Model design and transformation initiatives, including
front-to-back process redesign and platform consolidation across the Securities
Finance business. Define and execute client value propositions, segmentation,
and channel strategies. Partner with Change Management and Operational
Excellence teams to ensure new products and processes are effectively adopted.
Manage a team of product professionals, setting clear goals, providing
direction, and maintaining accountability for delivery outcomes. Required
Qualifications & Skills 6-10 years of experience in product management or
product development within financial services, capital markets, or a related
field. Working knowledge of the securities financing ecosystem or related
capital markets products. Demonstrated experience leading digital product
development from concept to delivery, including ownership of roadmap, backlog,
and stakeholder alignment across global teams. Hands-on experience developing
and applying AI and Machine Learning solutions to address real business
problems and measurable outcomes. Ability to apply design thinking principles
to complex product challenges. Strong ability to manage competing priorities.
"""


def _seed_board(db_session, pfizer_applied_hours_ago, citi_applied_hours_ago):
    """Both postings on the pm board, matched to a signed-in user who applied.

    Returns (pfizer_job_id, citi_job_id).
    """
    from app.models import BaseResume, Job, JobMatch, SavedSearch, User

    user = db_session.query(User).first()
    db_session.add(BaseResume(
        user_id=user.id, filename="r.pdf", file_path="/tmp/r.pdf",
        content_type="application/pdf", extracted_text=RESUME,
        years_experience=10,
    ))
    # Posted relative to now: the pm board keeps 2 days, so a hardcoded date
    # would make this test start failing on its own.
    posted = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=20)
    pfizer = Job(
        source="workday", company="Pfizer",
        title="Senior Product Manager, Data Products",
        normalized_title="senior product manager, data products",
        url="https://pfizer.wd1.myworkdayjobs.com/en-US/PfizerCareers/job/"
            "United-States---New-York---New-York-City/"
            "Senior-Product-Manager--Data-Products_4958954-1",
        city="nyc", location="United States - New York - New York City",
        description=PFIZER_DESCRIPTION, vertical="pm", is_technical=True,
        salary_min=124400, salary_max=207400,
        salary_label="$124,400 - $207,400", posted_at=posted,
    )
    citi = Job(
        source="workday", company="Citigroup",
        title="Securities Finance Product Manager, Vice President",
        normalized_title="securities finance product manager, vice president",
        url="https://citi.wd5.myworkdayjobs.com/en-US/2/job/"
            "New-York-New-York-United-States/"
            "Securities-Finance-Product-Developer---VP_26973296-1",
        city="nyc", location="New York New York United States",
        description=CITI_DESCRIPTION, vertical="pm", is_technical=True,
        salary_min=129840, salary_max=194760,
        salary_label="$129,840 - $194,760", posted_at=posted,
    )
    db_session.add_all([pfizer, citi])
    db_session.commit()

    search = db_session.query(SavedSearch).filter(
        SavedSearch.user_id == user.id, SavedSearch.vertical == "pm"
    ).one()
    now = datetime.now(timezone.utc)
    db_session.add_all([
        JobMatch(saved_search_id=search.id, user_id=user.id, job_id=pfizer.id,
                 applied_at=now - timedelta(hours=pfizer_applied_hours_ago)),
        JobMatch(saved_search_id=search.id, user_id=user.id, job_id=citi.id,
                 applied_at=now - timedelta(hours=citi_applied_hours_ago)),
    ])
    db_session.commit()
    return pfizer.id, citi.id


def test_both_postings_read_as_strong_fits():
    from app.fit import build_profile, score_fit

    profile = build_profile(RESUME, years=10)
    pfizer = score_fit(profile, "Senior Product Manager, Data Products",
                       PFIZER_DESCRIPTION, "pm")
    citi = score_fit(profile, "Securities Finance Product Manager, Vice President",
                     CITI_DESCRIPTION, "pm")

    for fit in (pfizer, citi):
        assert fit["score"] >= 85, fit["summary"]
        assert fit["label"] == "Strong fit"
        assert fit["tone"] == "strong"
        assert fit["low_signal"] is False


def test_a_years_range_resolves_to_the_top_of_the_range():
    """"6+ years" is 6; "6-10 years" is 10, not 6.

    Taking the bottom of a range would make a 10-year candidate look like they
    are four years over the bar, and being far over the requirement costs
    score (test_being_far_over_the_requirement_is_not_a_perfect_fit).
    """
    from app.fit import build_profile, score_fit

    profile = build_profile(RESUME, years=10)
    pfizer = score_fit(profile, "Senior Product Manager, Data Products",
                       PFIZER_DESCRIPTION, "pm")
    citi = score_fit(profile, "Securities Finance Product Manager, Vice President",
                     CITI_DESCRIPTION, "pm")

    assert "10 yrs vs 6 required" in pfizer["summary"]
    assert "10 yrs vs 10 required" in citi["summary"]


def test_securities_finance_product_role_is_not_downranked_as_brokerage():
    """The narrowest case the securities downrank has to get right.

    This posting says "securities financing", "broker-dealers" and "capital
    markets" and is still a product-management job — the vocabulary that sinks
    a card is retail sales-practice supervision (annuities, Series 7, unit
    investment trusts), not the asset class a real product manages.
    """
    from app.fit import build_profile, off_track_signals, score_fit

    profile = build_profile(RESUME, years=10)
    fit = score_fit(profile, "Securities Finance Product Manager, Vice President",
                    CITI_DESCRIPTION, "pm")

    assert off_track_signals(CITI_DESCRIPTION, "pm") == []
    assert "Reads as" not in fit["summary"]
    assert "securities / brokerage" not in fit["summary"]


def test_the_pair_renders_as_one_new_york_group(signed_in_client, db_session):
    _seed_board(db_session, pfizer_applied_hours_ago=5, citi_applied_hours_ago=4)

    body = signed_in_client.get("/dashboard").get_data(as_text=True)

    # One city section holding both cards.
    assert body.count('class="match-section"') == 1
    assert 'data-city-section="New York, NY"' in body
    assert '<strong class="match-count">2</strong>' in body

    assert "Senior Product Manager, Data Products" in body
    assert "Securities Finance Product Manager, Vice President" in body
    assert "$124,400 - $207,400" in body
    assert "$129,840 - $194,760" in body
    # Revenue comes from the company table, not the posting.
    assert "$64B rev" in body
    assert "$81B rev" in body
    # Both badges render green: the score itself moves with the resume, the
    # tone is the claim.
    assert body.count('class="fit-badge fit-strong"') == 2
    assert body.count("&middot; Strong fit") == 2


def test_applied_cards_show_what_is_left_of_the_grace_window(signed_in_client, db_session):
    """Applied 5 and 4 hours ago -> 19h and 20h left of BOARD_GRACE_HOURS."""
    _seed_board(db_session, pfizer_applied_hours_ago=5, citi_applied_hours_ago=4)

    body = signed_in_client.get("/dashboard").get_data(as_text=True)

    assert "leaves in 19h" in body
    assert "leaves in 20h" in body
    assert body.count('class="applied-badge"') == 2
    assert "display: inline-flex" in body


def test_an_applied_card_leaves_the_board_once_the_grace_window_closes(
    signed_in_client, db_session
):
    """The other half of the same rule: past 24h the card is gone, and the
    board says how many it is hiding rather than silently shrinking."""
    _seed_board(db_session, pfizer_applied_hours_ago=25, citi_applied_hours_ago=4)

    body = signed_in_client.get("/dashboard").get_data(as_text=True)

    assert "Senior Product Manager, Data Products" not in body
    assert "Securities Finance Product Manager, Vice President" in body
    assert '<strong class="match-count">1</strong>' in body
    assert "1 job you already applied to is hidden from this board" in body
