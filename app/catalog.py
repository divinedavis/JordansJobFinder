import os

TITLE_OPTIONS = [
    {"slug": "technical-product-manager", "label": "Product Manager", "vertical": "pm"},
    {"slug": "technical-program-manager", "label": "Program Manager", "vertical": "pm"},
    {"slug": "entry-finance-any", "label": "Any entry-level finance role", "vertical": "finance"},
    {"slug": "entry-finance-investment-banking", "label": "Investment Banking / S&T / Equity Research", "vertical": "finance"},
    {"slug": "entry-finance-fpa", "label": "Corporate Finance / FP&A Analyst", "vertical": "finance"},
    {"slug": "entry-finance-audit", "label": "Accounting / Audit Staff", "vertical": "finance"},
    {"slug": "entry-finance-commercial-banking", "label": "Commercial Banking Analyst", "vertical": "finance"},
]

TITLE_LABELS = {item["slug"]: item["label"] for item in TITLE_OPTIONS}
TITLE_VERTICALS = {item["slug"]: item["vertical"] for item in TITLE_OPTIONS}

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
}
# "any" finance slug = union of all finance keywords
TITLE_KEYWORDS["entry-finance-any"] = sorted({
    kw
    for slug, kws in TITLE_KEYWORDS.items()
    if slug.startswith("entry-finance-")
    for kw in kws
})

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
]
FINANCE_DEFAULT_CITIES = [
    "New York, NY", "Atlanta, GA", "Miami, FL",
    "Dallas, TX", "Houston, TX", "Washington, DC",
    "York, PA", "Lancaster, PA", "Philadelphia, PA",
    "Harrisburg, PA", "Baltimore, MD",
]
CITY_LABELS = {item["slug"]: item["label"] for item in CITY_OPTIONS}
SUPERUSER_EMAIL = os.getenv("SUPERUSER_EMAIL", "")


def title_choices():
    return TITLE_OPTIONS


def experience_choices():
    return EXPERIENCE_BUCKETS


def city_choices():
    return CITY_OPTIONS
