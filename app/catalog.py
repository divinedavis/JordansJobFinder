import os

from metros import (LABELS as METRO_LABELS, PA_REGIONAL as METRO_PA,
                    SC_REGIONAL as METRO_SC, TOP_20 as METRO_TOP_20)

TITLE_OPTIONS = [
    {"slug": "technical-product-manager", "label": "Product Manager", "vertical": "pm"},
    {"slug": "technical-program-manager", "label": "Program Manager", "vertical": "pm"},
    {"slug": "entry-finance-any", "label": "Any entry-level finance role", "vertical": "finance"},
    {"slug": "entry-finance-investment-banking", "label": "Investment Banking / S&T / Equity Research", "vertical": "finance"},
    {"slug": "entry-finance-fpa", "label": "Corporate Finance / FP&A Analyst", "vertical": "finance"},
    {"slug": "entry-finance-audit", "label": "Accounting / Audit Staff", "vertical": "finance"},
    {"slug": "entry-finance-commercial-banking", "label": "Commercial Banking Analyst", "vertical": "finance"},
    {"slug": "entry-sales-any", "label": "Any entry-level sales role", "vertical": "sales"},
    {"slug": "entry-sales-sdr-bdr", "label": "Sales / Business Development Rep (SDR/BDR)", "vertical": "sales"},
    {"slug": "entry-sales-account-executive", "label": "Account Executive (entry)", "vertical": "sales"},
    {"slug": "entry-sales-solutions-engineer", "label": "Sales / Solutions Engineer", "vertical": "sales"},
    {"slug": "entry-sales-inside-sales", "label": "Inside Sales / Sales Representative", "vertical": "sales"},
    {"slug": "it-project-program-manager", "label": "IT Project / Program Manager", "vertical": "it"},
    {"slug": "data-business-analyst", "label": "Data / Business Analyst", "vertical": "analyst"},
    {"slug": "hr-coordinator", "label": "HR Coordinator / Generalist (5+ yrs)", "vertical": "hr"},
    {"slug": "supply-chain-mgmt", "label": "Supply Chain Management", "vertical": "scm"},
    {"slug": "project-management", "label": "Project Management", "vertical": "project"},
]

TITLE_LABELS = {item["slug"]: item["label"] for item in TITLE_OPTIONS}
TITLE_VERTICALS = {item["slug"]: item["vertical"] for item in TITLE_OPTIONS}

# What users can actually pick: similar titles are combined into one option
# per track. The full TITLE_OPTIONS list above stays for validation/labels so
# legacy saved searches with sub-track slugs keep working.
SELECTABLE_TITLES = [
    # Combined selection: product, program, project, AND IT project/program
    # manager roles ride one option — a Product/Program Manager search also
    # matches IT-vertical and project-vertical jobs.
    {"slug": "technical-product-manager", "label": "Product / Program / Project Manager", "vertical": "pm"},
    {"slug": "entry-finance-any", "label": "Corporate Finance", "vertical": "finance"},
    {"slug": "entry-sales-any", "label": "Corporate Sales", "vertical": "sales"},
    {"slug": "data-business-analyst", "label": "Data / Business Analyst", "vertical": "analyst"},
    {"slug": "hr-coordinator", "label": "HR Coordinator / Generalist (5+ yrs)", "vertical": "hr"},
    {"slug": "supply-chain-mgmt", "label": "Supply Chain Management ($1B+)", "vertical": "scm"},
]

TITLE_KEYWORDS = {
    "technical-product-manager": ["product manager", "product management"],
    "technical-program-manager": ["program manager", "program management"],
    "entry-finance-investment-banking": [
        "investment banking", "ib analyst", "equity research",
        "sales & trading", "sales and trading", "s&t analyst",
        "research analyst",
    ],
    "entry-finance-fpa": [
        "financial analyst", "finance analyst", "fp&a", "fpa analyst",
        "treasury analyst", "corporate finance", "fund analyst",
        "fund accountant", "investment analyst", "investment associate",
    ],
    "entry-finance-audit": [
        "audit", "tax associate", "tax staff", "staff accountant",
        "audit associate", "audit staff", "external audit",
    ],
    "entry-finance-commercial-banking": [
        "credit analyst", "commercial banking", "underwriting",
        "underwriter", "loan officer", "portfolio analyst",
    ],
    # 2026-07-19: corporate-finance-department ICs beyond the classic
    # analyst tracks — risk/compliance, actuarial, quant, pricing, fund
    # operations, client service.
    "data-business-analyst": [
        "data analyst", "business analyst", "business intelligence",
        "bi analyst", "analytics analyst", "product analyst",
        "product operations", "business systems analyst",
        "reporting analyst", "insights analyst",
    ],
    "entry-finance-risk-compliance": [
        "risk analyst", "compliance analyst", "compliance officer",
        "aml", "kyc", "financial crimes", "sanctions screening",
        "actuarial", "actuary", "quantitative analyst", "quant analyst",
        "pricing analyst", "revenue analyst", "fund operations",
        "middle office", "client service associate", "reconciliation analyst",
    ],
}
# "any" finance slug = union of all finance keywords
TITLE_KEYWORDS["entry-finance-any"] = sorted({
    kw
    for slug, kws in TITLE_KEYWORDS.items()
    if slug.startswith("entry-finance-")
    for kw in kws
})

TITLE_KEYWORDS.update({
    "entry-sales-sdr-bdr": [
        "sales development representative", "sdr",
        "business development representative", "bdr",
        "sales development", "business development rep",
        "outbound sales", "outbound development",
    ],
    "entry-sales-account-executive": [
        "account executive", "ae i", "ae ii",
        "associate account executive", "junior account executive",
        "commercial account executive",
    ],
    "entry-sales-solutions-engineer": [
        "sales engineer", "solutions engineer", "solutions consultant",
        "pre-sales", "presales", "technical account",
    ],
    "entry-sales-inside-sales": [
        "inside sales", "sales representative", "sales rep",
        "sales associate", "client advisor", "retail sales",
        "sales specialist",
    ],
})
# "any" sales slug = union of all sales keywords
TITLE_KEYWORDS["entry-sales-any"] = sorted({
    kw
    for slug, kws in TITLE_KEYWORDS.items()
    if slug.startswith("entry-sales-")
    for kw in kws
})

TITLE_KEYWORDS["it-project-program-manager"] = [
    "project manager", "program manager",
    "project management", "program management",
]

# HR track: coordinator roles plus the level directly above (generalist /
# specialist). "senior hr coordinator" matches via the coordinator substring.
TITLE_KEYWORDS["hr-coordinator"] = [
    "hr coordinator", "human resources coordinator",
    "people operations coordinator", "hr operations coordinator",
    "hr generalist", "human resources generalist",
    "hr specialist", "human resources specialist",
]

# Supply chain management: any role in the supply-chain / logistics /
# procurement function (analyst through manager). Kept in sync with
# scraper_scm.py::SCM_KEYWORDS.
TITLE_KEYWORDS["supply-chain-mgmt"] = [
    "supply chain", "logistics", "procurement", "sourcing", "purchasing",
    "materials manager", "materials management", "demand planning",
    "supply planning", "inventory", "distribution", "warehouse",
    "fulfillment", "s&op", "buyer", "commodity manager", "category manager",
    "supply chain planner", "operations planner", "logistics coordinator",
]

# Project management: project-management roles across any industry. Kept in
# sync with app/matching.py::PROJECT_KEYWORDS and scraper_project.py.
TITLE_KEYWORDS["project-management"] = [
    "project manager", "project management", "project coordinator",
    "project lead", "project analyst", "project specialist",
    "project director", "project administrator", "pmo",
    "program manager", "program management",
]

EXPERIENCE_BUCKETS = [
    {"slug": "0-2", "label": "0-2 years"},
    {"slug": "3-6", "label": "3-6 years"},
    {"slug": "7-9", "label": "7-9 years"},
    {"slug": "10+", "label": "10+ years"},
]

# Every metro is covered for every user as of 2026-07-21 — the city picker is
# gone, so these are no longer "options" so much as the fixed board layout.
# Ordered by metro size (metros.ALL_METROS is match-order, not population), so
# the dashboard groups big markets first.
CITY_OPTIONS = [
    {"slug": slug, "label": METRO_LABELS[slug]}
    for slug in (*METRO_TOP_20, *METRO_PA, *METRO_SC)
]
ALL_CITY_LABELS = [item["label"] for item in CITY_OPTIONS]
# Every user's saved search covers every metro. Kept as a name because a lot of
# call sites still ask for "the default cities".
DEFAULT_CITIES = list(ALL_CITY_LABELS)
# Every track now covers every metro (2026-07-21). The per-vertical city sets
# these names used to hold are gone along with the picker: each existed to
# express "this track only serves these markets", and none of them do anymore.
# The names survive because VERTICAL_DEFAULT_CITIES and several call sites
# still reference them.
FINANCE_DEFAULT_CITIES = list(ALL_CITY_LABELS)
SALES_DEFAULT_CITIES = list(ALL_CITY_LABELS)
IT_DEFAULT_CITIES = list(ALL_CITY_LABELS)
HR_DEFAULT_CITIES = list(ALL_CITY_LABELS)
ANALYST_DEFAULT_CITIES = list(ALL_CITY_LABELS)
SCM_DEFAULT_CITIES = list(ALL_CITY_LABELS)
PROJECT_DEFAULT_CITIES = list(ALL_CITY_LABELS)
# Vertical -> fixed default city set used when a non-PM title is selected.
VERTICAL_DEFAULT_CITIES = {
    "analyst": ANALYST_DEFAULT_CITIES,
    "finance": FINANCE_DEFAULT_CITIES,
    "sales": SALES_DEFAULT_CITIES,
    "it": IT_DEFAULT_CITIES,
    "hr": HR_DEFAULT_CITIES,
    "scm": SCM_DEFAULT_CITIES,
    "project": PROJECT_DEFAULT_CITIES,
}
CITY_LABELS = {item["slug"]: item["label"] for item in CITY_OPTIONS}
SUPERUSER_EMAIL = os.getenv("SUPERUSER_EMAIL", "")
# Owner/admin accounts (billing-exempt, unlimited cities, never search-locked,
# feedback inbox, Pro features). SUPERUSER_EMAIL is the primary owner;
# ADMIN_EMAILS adds co-owners (comma-separated). Both are normalized to a set
# of lowercased addresses in ADMIN_EMAILS_SET below.
ADMIN_EMAILS_SET = {
    e.strip().lower()
    for e in (SUPERUSER_EMAIL + "," + os.getenv("ADMIN_EMAILS", "")).split(",")
    if e.strip()
}


def title_choices():
    return SELECTABLE_TITLES


def experience_choices():
    return EXPERIENCE_BUCKETS


def city_choices():
    return CITY_OPTIONS
