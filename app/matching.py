from typing import Optional

from corporate_filter import is_corporate_role
from .catalog import ADMIN_EMAILS_SET, CITY_LABELS, TITLE_KEYWORDS, TITLE_VERTICALS

EXCLUDE_TITLES = ["governance"]
# Companies the user never wants to see on the dashboard, matched
# case-insensitively against the normalized company name.
EXCLUDE_COMPANIES = {"scale ai", "google", "celonis", "tjx", "pagerduty", "etsy", "broadridge", "asana"}
# Management titles are never IC finance/sales roles — always excluded.
FINANCE_MANAGEMENT_NEGATIVE = (
    "staff vp", "vp ", " vp", "director", "head of", "chief",
    "managing director", "vice president",
)
SALES_MANAGEMENT_NEGATIVE = (
    "staff vp", "vp ", " vp", "director", "head of", "chief",
    "managing director", "vice president", "manager", "managing",
)
# Seniority markers only disqualify when the user's experience selection is
# entry-level (0-2). With more years selected, senior IC titles are in scope —
# the role level follows the years-of-experience choice.
IC_SENIORITY_TERMS = ("senior", "principal", "lead")
from .parsing import ParsedExperience, parse_experience_years


def normalize_text(value: str) -> str:
    import re
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _title_excluded(normalized: str) -> bool:
    return any(term in normalized for term in EXCLUDE_TITLES)


def company_excluded(company: str) -> bool:
    return normalize_text(company) in EXCLUDE_COMPANIES


def title_matches(title: str, selected_slug: str) -> bool:
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    keywords = TITLE_KEYWORDS.get(selected_slug, [])
    return any(keyword in normalized for keyword in keywords)


def title_matches_superuser_scope(title: str) -> bool:
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    return "product manage" in normalized or "program manage" in normalized


def title_is_entry_level_finance(title: str, entry_only: bool = True) -> bool:
    """Finance IC titles (analyst/associate vocabulary). Management is always
    excluded; senior/principal/lead ICs are excluded only when ``entry_only``
    (i.e. the user selected 0-2 years)."""
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    if not is_corporate_role(normalized):
        return False
    if any(neg in normalized for neg in FINANCE_MANAGEMENT_NEGATIVE):
        return False
    if entry_only and any(term in normalized for term in IC_SENIORITY_TERMS):
        return False
    finance_kws = TITLE_KEYWORDS.get("entry-finance-any", [])
    if any(kw in normalized for kw in finance_kws):
        return True
    # Catch the broader analyst/associate vocabulary as a fallback
    return "analyst" in normalized or "associate" in normalized


# HR track: coordinator roles and the level directly above (generalist /
# specialist). No salary requirement; directors/VPs stay out of scope.
HR_ROLE_KEYWORDS = (
    "hr coordinator", "human resources coordinator",
    "people operations coordinator", "hr operations coordinator",
    "hr generalist", "human resources generalist",
    "hr specialist", "human resources specialist",
)
HR_NEGATIVE_KEYWORDS = (
    "director", "vice president", " vp", "vp ", "head of", "chief",
    "intern", "internship",
)


def title_is_hr(title: str) -> bool:
    """HR coordinator/generalist/specialist titles ('senior' variants pass)."""
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    if not is_corporate_role(normalized):
        return False
    if any(neg in normalized for neg in HR_NEGATIVE_KEYWORDS):
        return False
    return any(kw in normalized for kw in HR_ROLE_KEYWORDS)


# Supply chain management track: any role in the supply-chain / logistics /
# procurement function. Kept in sync with scraper_scm.py::SCM_KEYWORDS.
SCM_KEYWORDS = (
    "supply chain", "logistics", "procurement", "sourcing", "purchasing",
    "materials manager", "materials management", "demand planning",
    "supply planning", "inventory", "distribution", "warehouse",
    "fulfillment", "s&op", "buyer", "commodity manager", "category manager",
    "supply chain planner", "operations planner", "logistics coordinator",
    # 2026-07-19: manufacturing-operations ICs (the track covers supply chain
    # AND manufacturing ops at $1B+ employers). Keep in sync with
    # scraper_scm.py::SCM_KEYWORDS.
    "production planner", "master scheduler", "production scheduler",
    "quality engineer", "quality analyst", "supplier quality",
    "manufacturing engineer", "process engineer", "industrial engineer",
    "continuous improvement", "lean six sigma", "ehs specialist",
)
SCM_NEGATIVE_KEYWORDS = ("intern", "internship")


# Data / Business Analyst track (2026-07-19): analytics ICs across every
# industry. Finance-track vocabulary (financial/credit/investment analyst…)
# is deliberately EXCLUDED so the same posting doesn't flip between
# verticals on successive syncs (DB upsert is by URL, last write wins).
# Keep in sync with scraper_analyst.py.
ANALYST_KEYWORDS = (
    "data analyst", "business analyst", "business intelligence",
    "bi analyst", "bi developer", "analytics analyst", "product analyst",
    "product operations", "business systems analyst", "reporting analyst",
    "insights analyst", "data quality analyst", "marketing analyst",
    "operations analyst", "strategy analyst",
)
ANALYST_NEGATIVE_KEYWORDS = (
    "financial analyst", "finance analyst", "credit analyst",
    "investment analyst", "audit", "tax", "actuarial", "treasury",
    "intern", "internship",
    "director", "vice president", "vp,", "vp ", " vp", "head of", "chief",
)


def title_is_analyst(title: str, entry_only: bool = False) -> bool:
    """Data/business-analytics IC titles. Management always excluded;
    senior ICs excluded only for 0-2-years users (entry_only)."""
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    if not is_corporate_role(normalized):
        return False
    if any(neg in normalized for neg in ANALYST_NEGATIVE_KEYWORDS):
        return False
    if any(neg in normalized for neg in FINANCE_MANAGEMENT_NEGATIVE):
        return False
    if entry_only and any(term in normalized for term in IC_SENIORITY_TERMS):
        return False
    return any(kw in normalized for kw in ANALYST_KEYWORDS)


def title_is_scm(title: str) -> bool:
    """Supply-chain / logistics / procurement roles (analyst through manager)."""
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    if not is_corporate_role(normalized):
        return False
    if any(neg in normalized for neg in SCM_NEGATIVE_KEYWORDS):
        return False
    return any(kw in normalized for kw in SCM_KEYWORDS)


# Project Management track: project-management roles across any industry
# (construction, IT, ops, healthcare, …). Unlike the IT track, no technology
# signal is required — a plain "Project Manager" qualifies. Kept in sync with
# scraper_project.py::PROJECT_KEYWORDS.
PROJECT_KEYWORDS = (
    "project manager", "project management", "project coordinator",
    "project lead", "project analyst", "project specialist",
    "project director", "project administrator", "pmo",
    "program manager", "program management",
)
PROJECT_NEGATIVE_KEYWORDS = ("intern", "internship")


def title_is_project(title: str) -> bool:
    """Project-management roles (coordinator through director), any industry."""
    normalized = normalize_text(title)
    if not is_corporate_role(normalized):
        return False
    if any(neg in normalized for neg in PROJECT_NEGATIVE_KEYWORDS):
        return False
    return any(kw in normalized for kw in PROJECT_KEYWORDS)


# IT project/program manager track. The title must be a project- or
# program-management role AND carry an IT/technology signal — otherwise a
# "Project Manager" at an oil company (construction, facilities, …) leaks in.
IT_PM_ROLE_KEYWORDS = (
    "project manager", "program manager",
    "project management", "program management",
)
IT_TITLE_SIGNALS = (
    "information technology", "information systems", "information security",
    "technical", "technology", "software", "infrastructure", "cyber",
    "security", "cloud", "erp", "sap", "crm", "salesforce", "digital",
    "data", "application", "systems", "network", "devops", "agile",
    "scrum", "pmo", "implementation", "integration",
)
IT_NEGATIVE_KEYWORDS = (
    "construction", "civil", "clinical", "facilities", "hvac",
    "electrical", "mechanical", "plumbing", "landscap", "roofing",
    "wastewater", "highway", "bridge", "real estate", "property",
)


def title_is_it_pm(title: str) -> bool:
    """Project/program manager titles with an IT/technology signal."""
    import re
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    if not is_corporate_role(normalized):
        return False
    if any(neg in normalized for neg in IT_NEGATIVE_KEYWORDS):
        return False
    if not any(kw in normalized for kw in IT_PM_ROLE_KEYWORDS):
        return False
    # "IT" needs a word boundary ("recruit", "digital" would substring-match).
    if re.search(r"\bit\b", normalized):
        return True
    return any(sig in normalized for sig in IT_TITLE_SIGNALS)


def title_is_entry_level_sales(title: str, entry_only: bool = True) -> bool:
    """Heuristic mirror of title_is_entry_level_finance for sales roles."""
    normalized = normalize_text(title)
    if _title_excluded(normalized):
        return False
    if not is_corporate_role(normalized):
        return False
    if any(neg in normalized for neg in SALES_MANAGEMENT_NEGATIVE):
        return False
    if entry_only and any(term in normalized for term in IC_SENIORITY_TERMS):
        return False
    sales_kws = TITLE_KEYWORDS.get("entry-sales-any", [])
    if any(kw in normalized for kw in sales_kws):
        return True
    return False

def experience_bucket_matches(bucket: str, parsed: ParsedExperience) -> bool:
    if parsed.min_years is None and parsed.max_years is None:
        return False

    target_ranges = {
        "0-2": (0, 2),
        "3-6": (3, 6),
        "7-9": (7, 9),
        "10+": (10, None),
    }
    target_low, target_high = target_ranges[bucket]
    value_low = parsed.min_years or 0
    value_high = parsed.max_years

    if target_high is None:
        return value_low >= target_low or (value_high is not None and value_high >= target_low)

    if value_high is None:
        return target_low <= value_low <= target_high

    return not (value_high < target_low or value_low > target_high)


def candidate_qualifies(candidate_years: int, parsed: ParsedExperience) -> bool:
    """Whether a candidate with `candidate_years` of experience meets a job's
    parsed requirement: the required MINIMUM must not exceed what they have.
    (Band overlap is wrong for resume-derived years — a 10-year candidate
    must match an "8+ years" job.) Unparseable requirements stay excluded,
    matching the pre-resume behavior."""
    if parsed.min_years is None and parsed.max_years is None:
        return False
    return (parsed.min_years or 0) <= candidate_years


def experience_at_least(minimum_years: int, parsed: ParsedExperience) -> bool:
    if parsed.min_years is None and parsed.max_years is None:
        return False
    low = parsed.min_years or 0
    high = parsed.max_years
    return low >= minimum_years or (high is not None and high >= minimum_years)


def salary_meets_minimum(
    salary_min: Optional[int],
    salary_max: Optional[int],
    minimum_salary: int,
) -> bool:
    if salary_min is None and salary_max is None:
        return True
    if salary_max is not None:
        return salary_max >= minimum_salary
    if salary_min is not None:
        return salary_min >= minimum_salary
    return True


def match_job(title_slug: str, experience_bucket: str, title: str, description: str) -> bool:
    if not title_matches(title, title_slug):
        return False

    parsed = parse_experience_years(title, description)
    return experience_bucket_matches(experience_bucket, parsed)


def choose_cities(city_1: str, city_2: str, city_3: str) -> list[str]:
    return [city for city in [city_1, city_2, city_3] if city]


def location_matches_city(location: str, label: str) -> bool:
    """Whether a raw ATS location string is in the city named by 'City, ST'.

    Used for cities beyond the built-in metros: the job's location text must
    contain the city name AND a state signal (abbreviation or full name), so
    'Springfield, IL' doesn't claim a Springfield-MA posting.
    """
    from .uscities import STATE_NAMES, split_label

    loc = normalize_text(location)
    if not loc:
        return False
    city, st = split_label(label)
    if not st or city.lower() not in loc:
        return False
    st_lower = st.lower()
    state_name = STATE_NAMES.get(st, "").lower()
    return (
        f", {st_lower}" in loc
        or f" {st_lower} " in f"{loc} "
        or (state_name and state_name in loc)
    )


def city_from_slug(city_slug: str) -> str:
    return CITY_LABELS.get(city_slug, city_slug)


def is_superuser_email(email: Optional[str]) -> bool:
    # Open access: every signed-in user gets the wide superuser scope
    # (PM + PgM, 5+ years, $180K+) and bypasses the billing gates.
    return bool((email or "").strip())


def is_admin_email(email: Optional[str]) -> bool:
    """Only configured owner accounts may review feedback + skip billing gates.

    is_superuser_email() is intentionally open to every signed-in user, so it
    can't gate the feedback inbox — this stricter check matches the owner
    accounts (SUPERUSER_EMAIL plus any co-owners in ADMIN_EMAILS) exactly.
    In production that's divinejdavis@gmail.com and khaliefwhetstone@yahoo.com.
    """
    addr = (email or "").strip().lower()
    return bool(addr) and addr in ADMIN_EMAILS_SET


def match_job_for_user(
    title_slug: str,
    experience_bucket: str,
    title: str,
    description: str,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    user_email: Optional[str] = None,
    resume_years: Optional[int] = None,
) -> bool:
    """resume_years is the total experience read from the user's resume
    (None when they have no resume / no parseable dates). When present it is
    the authoritative seniority signal: callers also pass the derived band as
    experience_bucket, and the years-sensitive branches below use
    QUALIFICATION semantics (job's required minimum <= the candidate's years)
    instead of band overlap — a 10-year candidate must match an "8+ years"
    job, which band overlap would wrongly reject."""
    vertical = TITLE_VERTICALS.get(title_slug, "pm")
    parsed = parse_experience_years(title, description)

    if vertical == "finance":
        # Finance: the role LEVEL follows the user's years-of-experience
        # selection — senior IC titles are in scope past 0-2. No salary floor.
        entry_only = (experience_bucket or "0-2") == "0-2"
        if not title_is_entry_level_finance(title, entry_only=entry_only):
            return False
        if title_slug != "entry-finance-any" and not title_matches(title, title_slug):
            return False
        # If experience is parseable, require it to fit (defaults to 0-2).
        if parsed.min_years is not None or parsed.max_years is not None:
            if resume_years is not None:
                return candidate_qualifies(resume_years, parsed)
            return experience_bucket_matches(experience_bucket or "0-2", parsed)
        return True

    if vertical == "analyst":
        # Data/Business Analyst: level follows experience (like finance).
        # No salary floor — analytics postings often omit pay.
        entry_only = (experience_bucket or "0-2") == "0-2"
        if not title_is_analyst(title, entry_only=entry_only):
            return False
        if parsed.min_years is not None or parsed.max_years is not None:
            if resume_years is not None:
                return candidate_qualifies(resume_years, parsed)
            return experience_bucket_matches(experience_bucket or "0-2", parsed)
        return True

    if vertical == "hr":
        # HR coordinator/generalist: no salary requirement (postings without
        # pay still show) and no experience exclusion — the track serves a
        # 5+ years candidate, who qualifies for every coordinator/generalist
        # level (same reasoning as the IT track).
        return title_is_hr(title)

    if vertical == "it":
        # IT project/program manager: title heuristic only. No salary floor
        # (jobs without pay data still show) and no experience exclusion —
        # this track serves a 10+ years user who qualifies for every level,
        # so a "5+ years required" posting must not be filtered out.
        return title_is_it_pm(title)

    if vertical == "scm":
        # Supply chain management: title heuristic only (function match). No
        # salary floor or experience exclusion — the $1B+-employer and
        # South-Carolina-location constraints are applied by the scraper.
        return title_is_scm(title)

    if vertical == "project":
        # Project management: title heuristic only. No salary floor or
        # experience exclusion — same reasoning as SCM (the $1B+-employer and
        # location constraints are applied by the scraper).
        return title_is_project(title)

    if vertical == "sales":
        # Sales: same shape as finance — the level follows the experience
        # selection, no salary floor, optional per-track keyword check.
        entry_only = (experience_bucket or "0-2") == "0-2"
        if not title_is_entry_level_sales(title, entry_only=entry_only):
            return False
        if title_slug != "entry-sales-any" and not title_matches(title, title_slug):
            return False
        if parsed.min_years is not None or parsed.max_years is not None:
            if resume_years is not None:
                return candidate_qualifies(resume_years, parsed)
            return experience_bucket_matches(experience_bucket or "0-2", parsed)
        return True

    # PM/PgM (existing logic)
    if is_superuser_email(user_email):
        if not (
            title_matches_superuser_scope(title)
            and salary_meets_minimum(salary_min, salary_max, 180000)
        ):
            return False
        # Resume-derived seniority beats the blanket 5+ rule: the candidate
        # must MEET the job's required minimum (not band-overlap it).
        if resume_years is not None:
            return candidate_qualifies(resume_years, parsed)
        return experience_at_least(5, parsed)

    if not title_matches(title, title_slug):
        return False
    if resume_years is not None:
        return candidate_qualifies(resume_years, parsed)
    return experience_bucket_matches(experience_bucket, parsed)
