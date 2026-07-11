"""Verified >$1B-revenue employers with real South Carolina operations.

Each Workday/Greenhouse endpoint below was probed and returned HTTP 200 from
the production droplet IP on 2026-07-11 (see the probe recipe in CLAUDE.md).
This module is the TEMPLATE for the per-state big-employer rollout: one
registry of (company, verified ATS endpoint) tuples per state, imported by the
role-track scrapers so the state's $1B+ jobs surface across every job type.

SC metros (slug): charleston-sc, columbia-sc, greenville-sc, rock-hill-sc.

Not included (verified UNREACHABLE from the droplet — documented so they don't
get re-probed blindly):
  - BlueCross BlueShield of SC (ourhrconnect / SCBlues) — Workday WAF returns
    HTTP 422 to datacenter IPs (all version/site variants tried).

Still on unsupported ATS platforms (SuccessFactors / Oracle / SmartRecruiters /
UKG / BrassRing / Taleo), so NOT yet added — a follow-up wave once those
platforms are wired into scraper_ats_extra: Nucor, Volvo, Milliken, Timken, ZF,
AFL, Schaeffler, CommScope, Dominion Energy SC, Honeywell, Cummins, AgFirst,
Domtar, International Paper, BMW (Taleo), Bosch/Continental (SmartRecruiters),
Fluor (Eightfold), ScanSource (UKG), Lockheed (BrassRing).
"""

# (company, workday_tenant, wd_version, site) — all verified HTTP 200 2026-07-11.
SC_WORKDAY_1B = [
    ("Michelin",             "michelinhr",        3,  "Michelin"),                    # Greenville
    ("GE Vernova",           "gevernova",         5,  "Vernova_ExternalSite"),        # Greenville
    ("Trane Technologies",   "tranetechnologies", 12, "Trane_Technologies_Careers"),  # Columbia (Killian Rd)
    ("3M",                   "3m",                1,  "Search"),                      # Greenville
    ("KION Group",           "kiongroup",         3,  "KIONGroup"),                   # Charleston (Summerville)
    ("Sonoco",               "sonoco",            1,  "CorporateCareers"),            # Hartsville (Midlands)
    ("Prisma Health",        "prismahealth",      5,  "PrismaHealthCorporate"),       # Greenville + Columbia
    ("Duke Energy",          "dukeenergy",        1,  "Search"),                      # Upstate plants
    ("Unum / Colonial Life", "unum",              1,  "External"),                    # Columbia
    ("MUSC",                 "musc",              1,  "MUSC"),                        # Charleston
    ("Roper St. Francis",    "easyservice",       5,  "RoperStFrancisHealthcare"),    # Charleston
    ("LPL Financial",        "lplfinancial",      1,  "External"),                    # Rock Hill (Fort Mill)
    ("Movement Mortgage",    "movement",          1,  "Careers"),                     # Rock Hill (Fort Mill)
    ("Atrium Health",        "aah",               5,  "External"),                    # Rock Hill (Fort Mill)
    ("Boeing",               "boeing",            1,  "EXTERNAL_CAREERS"),            # Charleston (N. Charleston)
]

# (company, greenhouse_token) — verified HTTP 200 2026-07-11.
SC_GREENHOUSE_1B = [
    ("Red Ventures", "redventures"),  # Rock Hill (Fort Mill)
]
