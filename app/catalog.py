import os

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

DEFAULT_CITIES = ["New York, NY", "Atlanta, GA", "Miami, FL"]
CITY_OPTIONS = [
    {"slug": "new-york-ny", "label": "New York, NY"},
    {"slug": "atlanta-ga", "label": "Atlanta, GA"},
    {"slug": "miami-fl", "label": "Miami, FL"},
    {"slug": "san-francisco-ca", "label": "San Francisco, CA"},
    {"slug": "seattle-wa", "label": "Seattle, WA"},
    {"slug": "austin-tx", "label": "Austin, TX"},
    {"slug": "boston-ma", "label": "Boston, MA"},
    {"slug": "los-angeles-ca", "label": "Los Angeles, CA"},
    {"slug": "chicago-il", "label": "Chicago, IL"},
    {"slug": "washington-dc", "label": "Washington, DC"},
    {"slug": "dallas-tx", "label": "Dallas, TX"},
    {"slug": "houston-tx", "label": "Houston, TX"},
    {"slug": "york-pa", "label": "York, PA"},
    {"slug": "lancaster-pa", "label": "Lancaster, PA"},
    {"slug": "philadelphia-pa", "label": "Philadelphia, PA"},
    {"slug": "harrisburg-pa", "label": "Harrisburg, PA"},
    {"slug": "baltimore-md", "label": "Baltimore, MD"},
    {"slug": "tampa-fl", "label": "Tampa, FL"},
    {"slug": "orlando-fl", "label": "Orlando, FL"},
    {"slug": "jacksonville-fl", "label": "Jacksonville, FL"},
    {"slug": "florida-other", "label": "Florida (other)"},
    {"slug": "charleston-sc", "label": "Charleston, SC"},
    {"slug": "columbia-sc", "label": "Columbia, SC"},
    {"slug": "greenville-sc", "label": "Greenville, SC"},
    {"slug": "rock-hill-sc", "label": "Rock Hill, SC"},
]
FINANCE_DEFAULT_CITIES = [
    "New York, NY", "Atlanta, GA", "Miami, FL",
    "Dallas, TX", "Houston, TX", "Washington, DC",
    "York, PA", "Lancaster, PA", "Philadelphia, PA",
    "Harrisburg, PA", "Baltimore, MD",
]
# Sales mirrors finance: same 11 metros.
SALES_DEFAULT_CITIES = list(FINANCE_DEFAULT_CITIES)
# IT project/program track: central/eastern PA plus every Florida metro (the
# job just has to sit in one of these locations — HQ doesn't matter).
IT_DEFAULT_CITIES = [
    "Lancaster, PA", "Philadelphia, PA", "Harrisburg, PA",
    "Miami, FL", "Tampa, FL", "Orlando, FL", "Jacksonville, FL",
    "Florida (other)",
]
# HR coordinator track: the four PA metros, always — selecting the HR title
# pins these cities (the 3-city picker on the form is PM-specific).
# PA metros stay first (the track's original audience keeps its free-tier
# cities); the nationwide metros added 2026-07-19 are reachable on paid
# tiers or via a custom-city override.
HR_DEFAULT_CITIES = [
    "York, PA", "Lancaster, PA", "Philadelphia, PA", "Harrisburg, PA",
    "New York, NY", "Chicago, IL", "Phoenix, AZ", "San Diego, CA",
    "Houston, TX", "Dallas, TX",
]
# Data / Business Analyst track (2026-07-19): biggest analytics markets
# first; free plan caps to the first 3.
ANALYST_DEFAULT_CITIES = [
    "New York, NY", "Chicago, IL", "Dallas, TX", "Atlanta, GA",
    "Philadelphia, PA", "Phoenix, AZ", "Los Angeles, CA", "San Diego, CA",
    "Houston, TX", "Washington, DC",
]
# Supply chain management track: nationwide major metros since 2026-07-19
# (originally SC-only). Free plan caps to the first 3.
# 2026-07-19: expanded nationwide (originally SC-only). Free plan caps to the
# first 3; paid tiers reach deeper into the list.
SCM_DEFAULT_CITIES = [
    "Chicago, IL", "Philadelphia, PA", "Houston, TX", "Phoenix, AZ",
    "Dallas, TX", "New York, NY", "Los Angeles, CA", "San Diego, CA",
    "Jacksonville, FL", "Charleston, SC",
]
# Project management track: same four SC metros as SCM (pilot state). Free plan
# caps to the first 3.
PROJECT_DEFAULT_CITIES = list(SCM_DEFAULT_CITIES)
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
