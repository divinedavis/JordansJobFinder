import os

TITLE_OPTIONS = [
    {"slug": "technical-product-manager", "label": "Technical Product Manager"},
    {"slug": "technical-program-manager", "label": "Technical Program Manager"},
]

TITLE_LABELS = {item["slug"]: item["label"] for item in TITLE_OPTIONS}

TITLE_KEYWORDS = {
    "technical-product-manager": ["product manager", "product management"],
    "technical-program-manager": ["program manager", "program management"],
}

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
]
CITY_LABELS = {item["slug"]: item["label"] for item in CITY_OPTIONS}
SUPERUSER_EMAIL = os.getenv("SUPERUSER_EMAIL", "")


def title_choices():
    return TITLE_OPTIONS


def experience_choices():
    return EXPERIENCE_BUCKETS


def city_choices():
    return CITY_OPTIONS
