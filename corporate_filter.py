"""Shared corporate-only filter for the finance + sales verticals.

Jordan wants corporate roles only — not in-store retail, field merchandising,
or plant-floor jobs. The entry-level title heuristics key on broad words like
"associate"/"sales", which otherwise pull in things like TJX "Merchandise
Associate", Comcast "Xfinity Retail Service Associate", Hershey "Part-Time
Territory Sales Associate", or PPG "Production Associate".

This module lives at the repo root (not inside the `app` package) so the
standalone cron scrapers (scraper_finance.py / scraper_sales.py) and the Flask
app's matching layer (app/matching.py) share one source of truth. It has no
third-party imports so either side can pull it in cheaply.
"""

# Substrings (matched case-insensitively) that mark a title as an in-store
# retail, field-merchandising, or plant-floor job rather than a corporate role.
# Kept deliberately specific — e.g. "stockroom"/"stock associate" rather than a
# bare "stock" (which would wrongly catch corporate "Stock Plan Analyst"), and
# "production associate" rather than a bare "production".
NON_CORPORATE_NEGATIVE = (
    "retail",
    "in-store", "in store", "store associate", "store cleaning",
    "merchandise", "merchandising",
    "cashier",
    "stockroom", "stock room", "stocker", "stock associate",
    "backroom", "back room",
    "sales floor", "floor associate",
    "loss prevention",
    "warehouse", "fulfillment", "distribution center",
    "production associate", "production operator",
    "production worker", "production technician",
    "teller", "barista", "custodian", "cleaning",
    "seasonal", "part time", "part-time", "part - time", "temporary", "temp ",
    "territory sales associate", "parts sales", "event sales",
)


def is_corporate_role(title: str) -> bool:
    """Return False when the title looks like an in-store retail, field
    merchandising, or plant-floor job rather than a corporate position."""
    t = (title or "").lower()
    return not any(term in t for term in NON_CORPORATE_NEGATIVE)
