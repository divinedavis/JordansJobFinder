"""How well a user's base resume matches a posting.

Deliberately deterministic — no model call. Every card on the board gets a
score, so an API-backed score would be a per-card cost on every page load, and
it would vanish exactly when the tailoring API is down (see
``resumes.ai_tailoring_status``) — which is when the board still has to be
useful. It also has to be *explainable*: a number the user can't interrogate is
worse than no number, so every score ships with the skills it matched and the
ones it didn't.

The score answers one question: **of the things this posting actually asks for,
how many does the resume already show?** Not "is this person good" — coverage
of the posting's own asks, the candidate's years against the years the posting
requires, and whether the title is the job they already do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .matching import parse_experience_years

# Curated rather than "every word in the posting": untargeted token overlap
# scores "the", "team" and "role" as skills and every job comes out an 80%
# match.
#
# Canonical skill -> the surface forms that mean it. A resume says "Technical
# Program Manager" where a posting says "program management"; without the
# aliases a ten-year program manager scored 1-of-10 against a program manager
# job. Everything is matched case-insensitively on word boundaries.
SKILL_ALIASES = {
    # Cloud / platform
    "aws": ("amazon web services",),
    "azure": (), "gcp": ("google cloud",),
    "cloud migration": ("cloud modernization", "migrate to the cloud", "cloud transformation"),
    "kubernetes": ("k8s",), "docker": (), "terraform": (),
    "microservices": (), "serverless": (),
    "ci/cd": ("continuous integration", "continuous delivery"),
    "devops": (), "sre": ("site reliability",),
    "infrastructure": ("infrastructure modernization",),
    "platform modernization": ("application modernization", "legacy modernization"),
    # Data
    "sql": (), "python": (), "etl": ("data pipelines", "data pipeline"),
    "data warehouse": ("data warehousing", "data lake"),
    "snowflake": (), "databricks": (), "kafka": (),
    "tableau": (), "power bi": (), "looker": (),
    "data governance": (),
    "analytics": ("analytical", "data analysis", "data analytics"),
    "reporting": ("reports", "status reporting"),
    "dashboards": ("dashboard", "executive dashboards"),
    "a/b testing": ("experimentation", "split testing"),
    "machine learning": ("ml models",),
    "artificial intelligence": ("ai/ml", "agentic ai"),
    "llm": ("large language model", "generative ai", "genai"),
    "sap bw": (), "big data": (),
    # Product
    "product management": ("product manager", "product owner", "product lifecycle"),
    "product strategy": (), "roadmap": ("roadmaps", "product roadmap", "roadmapping"),
    "backlog": ("backlog management", "backlog refinement", "backlog grooming"),
    "user research": ("customer research", "voice of the customer"),
    "user experience": ("ux", "user-centric", "user centric"),
    "customer journey": ("journey mapping",),
    "go to market": ("go-to-market", "gtm"),
    "product launch": ("launches", "launch management"),
    "discovery": (), "figma": (), "prototyping": ("prototypes", "wireframes"),
    "mvp": (), "pricing": (), "competitive analysis": ("market research",),
    # Program / project / delivery
    "program management": ("program manager", "technical program", "tpm"),
    "project management": ("project manager", "pmo", "project delivery"),
    "agile": ("agile delivery",), "scrum": ("scrum master",), "kanban": (),
    "safe": ("scaled agile",),
    "sprint planning": ("sprints", "daily standups", "standups"),
    "retrospectives": ("retros",),
    "jira": (), "confluence": (), "smartsheet": (), "asana": (),
    "monday.com": (), "ms project": ("microsoft project",), "waterfall": (),
    "pmp": (),
    "risk management": ("risk register", "risk mitigation", "risk assessment", "raid log"),
    "dependencies": ("dependency management",),
    "milestones": ("milestone",),
    "stakeholder management": ("stakeholders", "stakeholder engagement"),
    "change management": ("adoption strategy", "adoption strategies"),
    "release management": ("go-live", "go live", "cutover", "deployment readiness"),
    "resource planning": ("capacity planning", "workforce planning"),
    "governance": (),
    # Engineering-adjacent
    "api": ("apis", "api development", "rest", "graphql"),
    "integration": ("integrations", "system integration"),
    "architecture": ("system design", "solution architecture"),
    "technical documentation": ("documentation",),
    "requirements gathering": ("requirements", "user stories", "acceptance criteria",
                               "business requirements"),
    "qa": ("quality assurance", "testing"),
    "automation": ("automated", "automating"),
    # Business / finance
    "p&l": ("profit and loss",), "budget": ("budgets", "budgeting"),
    "forecasting": ("forecast",), "financial modeling": (),
    "cost reduction": ("cost savings", "cost optimization"),
    "revenue growth": (), "roi": (), "business case": (),
    "kpi": ("kpis", "key performance indicators"),
    "okr": ("okrs",), "metrics": (),
    "vendor management": ("vendor coordination", "vendors", "third party"),
    "procurement": ("sourcing",), "contract negotiation": ("contracts",),
    "compliance": ("regulatory", "sox", "audit"),
    "due diligence": (),
    "wealth management": ("private wealth", "pwm"),
    "asset management": (), "capital markets": (), "trading": (),
    "payments": (), "banking": ("financial services",), "fintech": (),
    "underwriting": (),
    # Enterprise systems
    "salesforce": (), "workday": (), "servicenow": (), "sap": (),
    "oracle": (), "netsuite": (), "sharepoint": (),
    "erp": (), "crm": (), "saas": (), "hris": (),
    # Sales / marketing
    "pipeline": ("sales pipeline",), "quota": (), "prospecting": (),
    "account management": (), "b2b": (),
    "lead generation": ("demand generation",), "seo": (), "campaign": ("campaigns",),
    # People / ops
    "recruiting": ("talent acquisition", "hiring"),
    "onboarding": (), "performance management": (),
    "employee engagement": (), "payroll": (),
    "supply chain": ("logistics",), "inventory": (), "manufacturing": (),
    "lean": (), "six sigma": (),
    "process improvement": ("continuous improvement", "operational excellence"),
    # Ways of working
    "cross functional": ("cross-functional", "cross functional teams"),
    "leadership": ("team leadership", "people leadership"),
    "mentoring": ("coaching",),
    "executive communication": ("executive presence", "c-suite", "executive stakeholders"),
    "facilitation": (),
    "global teams": ("distributed teams", "time zones", "offshore"),
}

# Surface form -> canonical skill.
_SURFACE_TO_SKILL = {}
for _canonical, _aliases in SKILL_ALIASES.items():
    for _surface in (_canonical,) + tuple(_aliases):
        _SURFACE_TO_SKILL[_surface.lower()] = _canonical

# One pass over the text instead of 300. A plain alternation of literals is
# linear — no nested quantifiers, so no ReDoS on an uploaded resume. Longest
# first so "product management" wins over "product".
_TERM_RE = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(re.escape(t) for t in sorted(_SURFACE_TO_SKILL, key=len, reverse=True))
    + r")(?![\w-])",
    re.I,
)

# Bound the scan: descriptions are scraped from arbitrary pages and a resume is
# user-uploaded. Neither should be able to make a page render slowly.
MAX_SCAN_CHARS = 20_000

# Title words that say nothing about the work ("Senior Product Manager II" and
# "Product Manager" are the same job for matching purposes).
_TITLE_NOISE = {
    "senior", "sr", "junior", "jr", "lead", "principal", "staff", "chief",
    "head", "vice", "president", "vp", "director", "i", "ii", "iii", "iv",
    "and", "of", "the", "for", "to", "with", "in", "at", "a", "an", "&",
    "remote", "hybrid", "onsite", "us", "usa", "new", "level", "grade",
}

# The score is a weighted blend of three signals. Skills dominate because they
# are what a posting actually lists; the other two keep a keyword-stuffed match
# from outranking the job the candidate already does.
WEIGHT_SKILLS = 0.55
WEIGHT_EXPERIENCE = 0.25
WEIGHT_TITLE = 0.20

# Below this many recognised terms, a posting hasn't said enough for skill
# coverage to mean anything (a link-only listing, or a description the scraper
# couldn't reach). Its weight moves to the signals that still hold.
MIN_TERMS_FOR_SIGNAL = 3

# Covering this share of a posting's named skills counts as full marks. A real
# posting lists 15-20 things and nobody has all of them; scoring raw coverage
# put a genuinely strong candidate at 45% and made every card look mediocre,
# which is worse than useless — the point of the number is to sort the board.
TARGET_COVERAGE = 0.6

LABELS = (
    (80, "Strong fit", "strong"),
    (65, "Good fit", "good"),
    (45, "Possible fit", "possible"),
    (0, "Stretch", "stretch"),
)


@dataclass(frozen=True)
class ResumeProfile:
    """What we know about the candidate, computed once per page render."""

    skills: frozenset
    years: Optional[int]
    text: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.skills and self.years is None


def terms_in(text: str) -> set:
    """The canonical skills named anywhere in the text."""
    if not text:
        return set()
    return {
        _SURFACE_TO_SKILL[m.group(0).lower()]
        for m in _TERM_RE.finditer(text[:MAX_SCAN_CHARS])
    }


def build_profile(resume_text: str, years: Optional[int]) -> ResumeProfile:
    text = (resume_text or "")[:MAX_SCAN_CHARS]
    return ResumeProfile(skills=frozenset(terms_in(text)), years=years, text=text.lower())


def _title_tokens(title: str) -> set:
    words = re.findall(r"[a-z]+", (title or "").lower())
    return {w for w in words if w not in _TITLE_NOISE and len(w) > 2}


def _experience_signal(profile: ResumeProfile, title: str, description: str) -> tuple:
    """(0-1 score, human phrase). Unknowns land mid-scale, never at zero — a
    posting that doesn't state a requirement isn't evidence against anyone."""
    parsed = parse_experience_years(title or "", description or "")
    required = parsed.min_years
    if required is None or profile.years is None:
        return 0.6, ""
    if profile.years >= required:
        # Well past the requirement is a fine match on skills but a weaker one
        # on level — a ten-year TPM against a one-year associate role shouldn't
        # sit at the top of the board as a "Strong fit".
        over = profile.years - required
        return (0.85 if over > 5 else 1.0), f"{profile.years} yrs vs {required} required"
    gap = required - profile.years
    if gap <= 2:
        return 0.7, f"{profile.years} yrs vs {required} required"
    return max(0.2, 1.0 - gap * 0.15), f"{profile.years} yrs vs {required} required"


def score_fit(profile: ResumeProfile, title: str, description: str) -> Optional[dict]:
    """Score one posting against one resume, or None if there's nothing to say."""
    if profile is None or profile.is_empty:
        return None

    asked = terms_in(description or "")
    # A term named in the title counts as asked for even when the description
    # is thin — "Senior Technical Program Manager" asks for program management.
    asked |= terms_in(title or "")
    matched = sorted(asked & profile.skills)
    missing = sorted(asked - profile.skills)

    low_signal = len(asked) < MIN_TERMS_FOR_SIGNAL
    coverage = (len(matched) / len(asked)) if asked else 0.0
    skill_signal = min(1.0, coverage / TARGET_COVERAGE)

    experience_signal, experience_phrase = _experience_signal(profile, title, description)

    title_words = _title_tokens(title)
    title_signal = (
        sum(1 for w in title_words if w in profile.text) / len(title_words)
        if title_words else 0.5
    )

    if low_signal:
        # Redistribute the skills weight rather than scoring a thin posting as
        # a bad match — the absence of a description is our problem, not the
        # candidate's.
        total = WEIGHT_EXPERIENCE + WEIGHT_TITLE
        raw = (experience_signal * WEIGHT_EXPERIENCE + title_signal * WEIGHT_TITLE) / total
    else:
        raw = (
            skill_signal * WEIGHT_SKILLS
            + experience_signal * WEIGHT_EXPERIENCE
            + title_signal * WEIGHT_TITLE
        )

    score = int(round(max(0.0, min(1.0, raw)) * 100))
    label, tone = next((lbl, tn) for floor, lbl, tn in LABELS if score >= floor)

    if low_signal:
        summary = "This posting lists too little detail to compare skills"
    else:
        summary = f"Matches {len(matched)} of {len(asked)} skills this posting names"
    if experience_phrase:
        summary = f"{summary} · {experience_phrase}"

    return {
        "score": score,
        "label": label,
        "tone": tone,
        "summary": summary,
        "matched": matched[:8],
        "missing": missing[:6],
        "low_signal": low_signal,
    }
