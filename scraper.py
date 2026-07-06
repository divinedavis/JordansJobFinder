#!/usr/bin/env python3
"""
Jordan's Job Finder — Expanded Multi-Company Scraper
-----------------------------------------------------
Cities   : NYC (VP only) | Atlanta | Miami | Dallas | Houston | DC | LA (VP or Senior)
Finance  : Top 500 finance + hedge funds with NYC / Atlanta / Miami presence
Tech     : Top 100 tech companies with NYC / Atlanta / Miami offices
Output   : /var/www/jordansjobfinder/jobs.html
Cron     : daily at 12:00 PM
"""

import json, re, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from app.parsing import (
    format_salary_label,
    normalize_numeric_language,
    parse_experience_years,
    parse_salary,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
SEEN_FILE   = SCRIPT_DIR / "seen_jobs.json"
OUTPUT_FILE = SCRIPT_DIR / "jobs.html"
LOG_FILE    = SCRIPT_DIR / "scraper.log"
STORE_FILE  = SCRIPT_DIR / "jobs_store.json"
SHARED_JOBS_FILE = SCRIPT_DIR / "shared_jobs.json"

# ── Filters ───────────────────────────────────────────────────────────────────
TARGET_ROLES      = ["product manager", "program manager",
                     "product management", "program management"]
VP_TERMS          = [r"\bvice president\b", r"\b vp\b", r"\bvp,", r"\(vp\)"]
SENIOR_TERMS      = [r"\bsenior\b", r"\bsr\b", r"\blead\b",
                     r"\bstaff\b", r"\bprincipal\b"]
EXCLUDE_SENIORITY = [r"senior vice", r"assistant vice", r"\bavp\b", r"\bsvp\b", r"\bgovernance\b",
                     r"\bdirector\b", r"\bmanaging director\b"]

NYC_LOCS     = ["new york", "nyc", "manhattan", "brooklyn", "jersey city"]
ATLANTA_LOCS = ["atlanta", "alpharetta", "buckhead", "sandy springs",
                "dunwoody", "midtown", "ga,", ", ga", "georgia"]
MIAMI_LOCS   = ["miami", "miami, fl", "miami fl", "miami, florida",
                "miami florida", "miami beach", "miami-dade", "greater miami",
                "south florida", "brickell", "coral gables", "doral",
                "fort lauderdale", "ft lauderdale", "aventura", "boca raton"]

DALLAS_LOCS  = ["dallas", "fort worth", "dfw", "plano", "irving",
                "arlington", "frisco", "richardson", "addison",
                "tx,", ", tx", "texas"]
HOUSTON_LOCS = ["houston", "the woodlands", "sugar land", "katy",
                "spring", "pasadena", "cypress", "pearland",
                "humble", "baytown"]
DC_LOCS      = ["washington", "d.c.", "dc", "arlington, va",
                "mclean", "tysons", "reston", "bethesda",
                "rockville", "silver spring", "fairfax",
                "alexandria", "northern virginia", "nova"]
# Specific LA-metro place names only (no broad ", ca"/"california" catch-all)
# so Bay Area / San Diego roles aren't misclassified as Los Angeles.
LA_LOCS      = ["los angeles", "l.a.", "greater los angeles", "socal",
                "santa monica", "culver city", "long beach", "pasadena",
                "burbank", "glendale", "el segundo", "marina del rey",
                "playa vista", "venice, ca", "west hollywood", "hawthorne",
                "gardena", "sherman oaks", "westwood", "century city",
                "torrance", "manhattan beach", "redondo beach", "inglewood",
                "van nuys", "studio city", "north hollywood", "woodland hills",
                "santa clarita", "calabasas", "beverly hills", "ventura"]

CITY_LABELS = {
    "nyc": "New York, NY",
    "atlanta": "Atlanta, GA",
    "miami": "Miami, FL",
    "dallas": "Dallas, TX",
    "houston": "Houston, TX",
    "dc": "Washington, DC",
    "la": "Los Angeles, CA",
}

CITY_SEARCH = {
    "nyc": "New York",
    "atlanta": "Atlanta",
    "miami": "Miami",
    "dallas": "Dallas",
    "houston": "Houston",
    "dc": "Washington",
    "la": "Los Angeles",
}

AMAZON_LOCATIONS = {
    "nyc": "New York,New York,United States",
    "atlanta": "Atlanta,Georgia,United States",
    "miami": "Miami,Florida,United States",
    "dallas": "Dallas,Texas,United States",
    "houston": "Houston,Texas,United States",
    "dc": "Washington,District of Columbia,United States",
    "la": "Los Angeles,California,United States",
}

MIN_SALARY   = 180_000
# Salary minimum is enforced for NYC only — every other city is salary-optional
# (many postings outside NYC list no salary, and most non-NYC states don't mandate it).
# "extra" = a user-selected city beyond the built-in metros (state-grouped
# picker); those markets rarely publish salaries, so they're salary-optional.
SALARY_OPTIONAL_CITIES = {"atlanta", "miami", "dallas", "houston", "dc", "la", "extra"}
VALID_POST_DAYS = 2
TECH_THRESHOLD  = 3
TECH_SIGNALS = [
    "agile", "scrum", "sprint", "api", "cloud", "aws", "azure", "gcp",
    "engineering", "software", "infrastructure", "platform", "microservices",
    "machine learning", "artificial intelligence", " ai ", "devops",
    "kubernetes", "docker", "ci/cd", "data pipeline", "architecture",
    "roadmap", "tech stack", "jira", "confluence", "technical",
    "technology", "digital transformation", "system design",
    "backend", "frontend", "data", "analytics", "fintech", "payments",
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}

# ── Company Configs ────────────────────────────────────────────────────────────
# (name, tenant, workday_ver, site_name, city)
# city: "nyc" | "atlanta" | "miami"
WORKDAY_COMPANIES = [
    # ── Finance · NYC ──────────────────────────────────────────────────────────
    ("TIAA",             "tiaa",          1,   "Search",                  "nyc"),
    ("Travelers",        "travelers",     5,   "External",                "nyc"),
    ("Wells Fargo",      "wf",            1,   "WellsFargoJobs",          "nyc"),
    ("Bank of America",  "ghr",           1,   "Lateral-US",              "nyc"),
    ("Morgan Stanley",   "ms",            5,   "External",                "nyc"),
    ("BlackRock",        "blackrock",     1,   "BlackRock_Professional",  "nyc"),
    ("Vanguard",         "vanguard",      5,   "vanguard_external",       "nyc"),
    ("Fidelity",         "fmr",           1,   "FidelityCareers",         "nyc"),
    ("State Street",     "statestreet",   1,   "Global",                  "nyc"),
    ("T. Rowe Price",    "troweprice",    5,   "TRowePrice",              "nyc"),
    ("Prudential",       "pru",           5,   "Careers",                 "nyc"),
    ("AIG",              "aig",           1,   "aig",                     "nyc"),
    ("The Hartford",     "thehartford",   5,   "Careers_External",        "nyc"),
    ("Allstate",         "allstate",      5,   "allstate_careers",        "nyc"),
    ("Nationwide",       "nationwide",    1,   "Nationwide_Career",       "nyc"),
    ("Mastercard",       "mastercard",    1,   "CorporateCareers",        "nyc"),
    ("S&P Global",       "spgi",          5,   "SPGI_Careers",            "nyc"),
    ("Nasdaq",           "nasdaq",        1,   "US_External_Career_Site", "nyc"),
    ("CME Group",        "cmegroup",      1,   "cme_careers",             "nyc"),
    ("Blackstone",       "blackstone",    1,   "Blackstone_Careers",      "nyc"),
    ("Apollo",           "athene",        5,   "Apollo_Careers",          "nyc"),
    ("Millennium Mgmt",  "mlp",           5,   "mlpcareers",              "nyc"),
    ("FactSet",          "factset",       108, "FactSetCareers",          "nyc"),
    # ── Tech · NYC ─────────────────────────────────────────────────────────────
    ("Netflix",          "netflix",       1,   "Netflix",                 "nyc"),
    ("Salesforce",       "salesforce",    12,  "External_Career_Site",    "nyc"),
    ("Etsy",             "etsy",          5,   "Etsy_Careers",            "nyc"),
    ("Snap",             "snapchat",      1,   "snap",                    "nyc"),
    # ── Finance · Atlanta ──────────────────────────────────────────────────────
    ("Equifax",          "equifax",       1,   "equifax",                 "atlanta"),
    ("Global Payments",  "globalpayments",5,   "GPExternalCareers",       "atlanta"),
    ("Fiserv",           "fiserv",        5,   "fiserv",                  "atlanta"),
    ("Millennium Mgt ATL","mlp",          5,   "mlpcareers",              "atlanta"),
    ("S&P Global ATL",   "spgi",          5,   "SPGI_Careers",            "atlanta"),
    # ── Tech & Corporate · Atlanta ─────────────────────────────────────────────
    ("Delta Air Lines",  "delta",         5,   "Delta_External_Careers",  "atlanta"),
    ("Home Depot",       "ext",           5,   "HomeDepotExternalCareers","atlanta"),
    ("NCR Voyix",        "ncrvoyix",      5,   "NCRVoyixCareers",         "atlanta"),
    ("Norfolk Southern", "nssouthern",    1,   "NSCareers",               "atlanta"),
    ("UPS",              "ups",           5,   "UPS_External_Career_Site","atlanta"),
    ("Southern Company", "southerncompany",1,  "SoCo_External",           "atlanta"),
    ("Manhattan Assoc",  "mas",           5,   "MASCareers",              "atlanta"),
    ("Cox Enterprises",  "coxenterprises",5,   "CoxCareers",              "atlanta"),
    ("Genuine Parts",    "genuineparts",  1,   "GPC",                     "atlanta"),
    ("Salesforce ATL",   "salesforce",    12,  "External_Career_Site",    "atlanta"),
    ("NCR Atleos",       "ncratleos",     5,   "NCRAtleosCareers",        "atlanta"),
    # ── Finance · NYC (new) ────────────────────────────────────────────────────
    ("Deutsche Bank",    "db",            1,   "DBmanagement",            "nyc"),
    ("Barclays",         "barclays",      5,   "Barclays",                "nyc"),
    ("UBS",              "ubs",           1,   "UBS_Global",              "nyc"),
    ("BNY Mellon",       "bnymellon",     5,   "BNY_Mellon_Careers",      "nyc"),
    ("HSBC",             "hsbc",          5,   "HSBCCareer",              "nyc"),
    ("Nomura",           "nomura",        5,   "Nomura",                  "nyc"),
    ("Jefferies",        "jefferies",     5,   "Jefferies",               "nyc"),
    ("Ally Financial",   "ally",          5,   "ally",                    "nyc"),
    ("Citadel",          "citadel",       5,   "Citadel",                 "nyc"),
    ("D.E. Shaw",        "deshaw",        5,   "External",                "nyc"),
    ("Jane Street",      "janestreet",    5,   "External",                "nyc"),
    # ── Tech · NYC (new) ───────────────────────────────────────────────────────
    ("Microsoft",        "microsoftcareers", 5, "MicrosoftCareers",       "nyc"),
    ("Visa",             "visa",          5,   "Visa",                    "nyc"),
    ("PayPal",           "paypal",        5,   "paypal",                  "nyc"),
    ("Uber",             "uber",          5,   "External",                "nyc"),
    ("Spotify",          "spotify",       5,   "External",                "nyc"),
    ("ByteDance",        "bytedance",     5,   "External",                "nyc"),
    ("Workday Inc",      "workday",       5,   "workday",                 "nyc"),
    ("Plaid",            "plaid",         5,   "External",                "nyc"),
    # ── Enterprise · NYC + Atlanta (new) ───────────────────────────────────────
    ("IBM",              "ibm",           5,   "External",                "nyc"),
    ("Accenture",        "accenture",     5,   "AccentureCareers",        "nyc"),
    ("SAP",              "sap",           5,   "SAP",                     "nyc"),
    ("Oracle",           "oracle",        5,   "oracle",                  "nyc"),
    ("ServiceNow",       "servicenow",    5,   "External",                "nyc"),
    ("IBM ATL",          "ibm",           5,   "External",                "atlanta"),
    ("Accenture ATL",    "accenture",     5,   "AccentureCareers",        "atlanta"),
    ("SAP ATL",          "sap",           5,   "SAP",                     "atlanta"),
    ("Oracle ATL",       "oracle",        5,   "oracle",                  "atlanta"),
    ("ServiceNow ATL",   "servicenow",    5,   "External",                "atlanta"),
    ("IBM MIA",          "ibm",           5,   "External",                "miami"),
    ("Accenture MIA",    "accenture",     5,   "AccentureCareers",        "miami"),
    ("Oracle MIA",       "oracle",        5,   "oracle",                  "miami"),
    ("ServiceNow MIA",   "servicenow",    5,   "External",                "miami"),
    ("Salesforce MIA",   "salesforce",    12,  "External_Career_Site",    "miami"),
    ("Visa MIA",         "visa",          5,   "Visa",                    "miami"),
    ("PayPal MIA",       "paypal",        5,   "paypal",                  "miami"),
    ("Mastercard MIA",   "mastercard",    1,   "CorporateCareers",        "miami"),
    # ── Finance & Corporate · Atlanta (new) ────────────────────────────────────
    ("ICE",              "ice",           5,   "ice",                     "atlanta"),
    ("Honeywell",        "honeywell",     5,   "Honeywell",               "atlanta"),
    ("Elevance Health",  "elevancehealth",5,   "External",                "atlanta"),
    ("Roper Tech",       "roper",         5,   "External",                "atlanta"),
    ("Chick-fil-A",      "cfacorp",       5,   "CFA_External",            "atlanta"),
    ("Porsche Cars NA",  "porschecars",   5,   "External",                "atlanta"),
    ("Inspire Brands",   "inspirebrands", 5,   "External",                "atlanta"),
    # ── Fortune 1000 · Finance · NYC ──────────────────────────────────────────
    ("Capital One",      "capitalone",    1,   "Capital_One",             "nyc"),
    ("Synchrony",        "synchronyfinancial", 5, "careers",              "nyc"),
    ("Discover",         "discover",      5,   "Discover",                "nyc"),
    ("Guardian Life",    "guardianlife",  5,   "Guardian-Life-Careers",   "nyc"),
    ("MassMutual",       "massmutual",    1,   "MMAscendCareers",         "nyc"),
    ("Northwestern Mut", "northwesternmutual", 5, "CORPORATE-CAREERS",   "nyc"),
    # ── Fortune 1000 · Pharma/Health · NYC ────────────────────────────────────
    ("Pfizer",           "pfizer",        1,   "PfizerCareers",           "nyc"),
    ("Johnson & Johnson","jj",            5,   "JJ",                      "nyc"),
    ("Bristol-Myers",    "bristolmyerssquibb", 5, "BMS",                  "nyc"),
    ("Merck",            "msd",           5,   "SearchJobs",              "nyc"),
    ("CVS Health",       "cvshealth",     1,   "CVS_Health_Careers",      "nyc"),
    ("Cigna",            "cigna",         5,   "cignacareers",            "nyc"),
    ("Humana",           "humana",        5,   "Humana_External_Career_Site", "nyc"),
    ("Cardinal Health",  "cardinalhealth",1,   "EXT",                     "nyc"),
    ("Abbott",           "abbott",        5,   "abbottcareers",           "nyc"),
    ("Becton Dickinson", "bdx",           1,   "EXTERNAL_CAREER_SITE_USA","nyc"),
    # ── Fortune 1000 · Media/Telecom · NYC ────────────────────────────────────
    ("Verizon",          "verizon",       12,  "verizon-careers",         "nyc"),
    ("AT&T",             "att",           1,   "ATTGeneral",              "nyc"),
    ("Comcast",          "comcast",       5,   "Comcast_Careers",         "nyc"),
    ("Walt Disney",      "disney",        5,   "disneycareer",            "nyc"),
    ("Warner Bros",      "warnerbros",    5,   "global",                  "nyc"),
    ("Fox Corp",         "fox",           1,   "Domestic",                "nyc"),
    ("PwC",              "pwc",           3,   "Global_Experienced_Careers", "nyc"),
    ("New York Times",   "nytimes",       5,   "NYT",                     "nyc"),
    # ── Fortune 1000 · Tech/Cyber · NYC ───────────────────────────────────────
    ("Cisco",            "cisco",         5,   "Cisco_Careers",           "nyc"),
    ("Intel",            "intel",         1,   "External",                "nyc"),
    ("CrowdStrike",      "crowdstrike",   5,   "crowdstrikecareers",      "nyc"),
    # ── Fortune 1000 · Consumer · NYC ─────────────────────────────────────────
    ("PVH Corp",         "pvh",           1,   "PVH_Careers",             "nyc"),
    # ── Fortune 1000 · Atlanta ────────────────────────────────────────────────
    ("Coca-Cola",        "coke",          1,   "coca-cola-careers",       "atlanta"),
    ("Truist Financial", "truist",        1,   "Careers",                 "atlanta"),
    ("Invesco",          "invesco",       1,   "IVZ",                     "atlanta"),
    ("Corpay",           "corpay",        103, "Ext_001",                 "atlanta"),
    ("Carter's",         "carters",       1,   "CartersCareers",          "atlanta"),
    ("Assurant",         "assurant",      1,   "Assurant_Careers",        "atlanta"),
    ("Veritiv",          "veritiv",       5,   "VeritivCareers",          "atlanta"),
    ("HD Supply",        "hdsupply",      1,   "External",                "atlanta"),
    ("Capital One ATL",  "capitalone",    1,   "Capital_One",             "atlanta"),
    ("Verizon ATL",      "verizon",       12,  "verizon-careers",         "atlanta"),
    ("AT&T ATL",         "att",           1,   "ATTGeneral",              "atlanta"),
    ("Cisco ATL",        "cisco",         5,   "Cisco_Careers",           "atlanta"),
    ("CVS Health ATL",   "cvshealth",     1,   "CVS_Health_Careers",      "atlanta"),
    # ── Fortune 1000 · Miami ──────────────────────────────────────────────────
    ("Norwegian Cruise", "nclh",          108, "NCLH_Careers",            "miami"),
    ("Ryder System",     "ryder",         5,   "RyderCareers",            "miami"),
    ("Lennar",           "lennar",        1,   "Lennar_Jobs",             "miami"),
    ("World Fuel Svc",   "wfscorp",       5,   "wfscareers",              "miami"),
    ("Capital One MIA",  "capitalone",    1,   "Capital_One",             "miami"),
    ("Verizon MIA",      "verizon",       12,  "verizon-careers",         "miami"),
    ("AT&T MIA",         "att",           1,   "ATTGeneral",              "miami"),
    ("Cisco MIA",        "cisco",         5,   "Cisco_Careers",           "miami"),
    ("Walt Disney MIA",  "disney",        5,   "disneycareer",            "miami"),

    # ── Dallas / Fort Worth ───────────────────────────────────────────────────
    ("AT&T DAL",         "att",            1,   "ATTGeneral",              "dallas"),
    ("Capital One DAL",  "capitalone",     1,   "Capital_One",             "dallas"),
    ("Texas Instruments","texasinstruments",5,  "TI_Careers",              "dallas"),
    ("Lockheed Martin DAL","lockheedmartin",5, "LMCO_Careers",            "dallas"),
    ("Deloitte DAL",     "deloitte",       5,   "DeloitteCareers",         "dallas"),
    ("CBRE DAL",         "cbre",           5,   "cbre_careers",            "dallas"),
    ("McKesson DAL",     "mckesson",       5,   "McKesson",                "dallas"),
    ("Kimberly-Clark",   "kimberlyclark",  5,   "GLOBAL",                  "dallas"),
    ("Jacobs DAL",       "jacobs",         5,   "Jacobs_Careers",          "dallas"),
    ("Tenet Healthcare", "tenethealth",    5,   "Careers",                 "dallas"),
    ("Southwest Airlines","southwestair",  5,   "SWA_Careers",             "dallas"),
    ("Toyota NA DAL",    "toyota",         5,   "ToyotaMotorsNA",          "dallas"),
    ("JPMorgan DAL",     "jpmc",           5,   "JPMC_Careers",            "dallas"),
    ("Goldman Sachs DAL","goldmansachs",   5,   "GS_Careers",             "dallas"),
    ("Cisco DAL",        "cisco",          5,   "Cisco_Careers",           "dallas"),
    ("Verizon DAL",      "verizon",        12,  "verizon-careers",         "dallas"),
    ("PepsiCo DAL",      "pepsico",        5,   "pepsicojobs",             "dallas"),
    ("Raytheon DAL",     "rtx",            5,   "RTX_Careers",             "dallas"),
    ("NTT Data DAL",     "nttdata",        5,   "NTTData_Careers",         "dallas"),
    ("Accenture DAL",    "accenture",      5,   "Accenture_Careers",       "dallas"),
    # ── Houston ───────────────────────────────────────────────────────────────
    ("Shell",            "shell",          5,   "Shell_Careers",            "houston"),
    ("HP Inc HOU",       "hpi",            5,   "HP_Careers",              "houston"),
    ("HP Enterprise",    "hpe",            5,   "HPE_Careers",             "houston"),
    ("ConocoPhillips",   "conocophillips", 5,   "ConocoPhillips_Careers",  "houston"),
    ("Phillips 66",      "phillips66",     5,   "Phillips66Careers",       "houston"),
    ("Halliburton",      "halliburton",    5,   "Halliburton_Careers",     "houston"),
    ("Baker Hughes",     "bakerhughes",    5,   "BH_Careers",             "houston"),
    ("Schlumberger",     "slb",            5,   "SLB_Careers",             "houston"),
    ("Sysco",            "sysco",          5,   "Sysco_Careers",           "houston"),
    ("Waste Management", "wm",             5,   "WM_Careers",             "houston"),
    ("Deloitte HOU",     "deloitte",       5,   "DeloitteCareers",         "houston"),
    ("Accenture HOU",    "accenture",      5,   "Accenture_Careers",       "houston"),
    ("JPMorgan HOU",     "jpmc",           5,   "JPMC_Careers",            "houston"),
    ("Capital One HOU",  "capitalone",     1,   "Capital_One",             "houston"),
    ("Oracle HOU",       "oracle",         5,   "Oracle_Careers",          "houston"),
    ("Chevron",          "chevron",        5,   "Chevron_Careers",         "houston"),
    ("ExxonMobil",       "exxonmobil",     5,   "ExxonMobil_Careers",     "houston"),
    ("NRG Energy",       "nrg",            5,   "NRG_Careers",             "houston"),
    ("Targa Resources",  "targaresources", 5,   "TargaResources",          "houston"),
    ("EOG Resources",    "eogresources",   5,   "EOG_Careers",             "houston"),
    # ── Washington DC / Northern Virginia ─────────────────────────────────────
    ("Capital One DC",   "capitalone",     1,   "Capital_One",             "dc"),
    ("Booz Allen",       "boozallen",      5,   "Booz_Allen_Careers",      "dc"),
    ("Deloitte DC",      "deloitte",       5,   "DeloitteCareers",         "dc"),
    ("Accenture DC",     "accenture",      5,   "Accenture_Careers",       "dc"),
    ("Lockheed Martin DC","lockheedmartin",5,  "LMCO_Careers",            "dc"),
    ("Northrop Grumman", "northropgrumman",5,   "NG_Careers",             "dc"),
    ("Raytheon DC",      "rtx",            5,   "RTX_Careers",             "dc"),
    ("General Dynamics", "gd",             5,   "GD_Careers",              "dc"),
    ("SAIC",             "saic",           5,   "SAIC_Careers",            "dc"),
    ("Leidos",           "leidos",         5,   "Leidos_Careers",          "dc"),
    ("BAE Systems DC",   "baesystems",     5,   "BAE_Careers",             "dc"),
    ("Fannie Mae",       "fanniemae",      5,   "FannieMae_Careers",       "dc"),
    ("Freddie Mac",      "freddiemac",     5,   "FreddieMac_Careers",      "dc"),
    ("Marriott",         "marriott",       5,   "Marriott_Careers",        "dc"),
    ("Hilton DC",        "hilton",         5,   "Hilton_Careers",          "dc"),
    ("Verizon DC",       "verizon",        12,  "verizon-careers",         "dc"),
    ("AWS DC",           "amazon",         5,   "Amazon_Careers",          "dc"),
    ("Microsoft DC",     "microsoft",      5,   "Microsoft_Careers",       "dc"),
    ("Oracle DC",        "oracle",         5,   "Oracle_Careers",          "dc"),
    ("JPMorgan DC",      "jpmc",           5,   "JPMC_Careers",            "dc"),
    ("Wells Fargo DC",   "wf",             1,   "WellsFargoJobs",          "dc"),

    # ── Fortune 1000 expansion (verified live 2026-05-18) ─────────────────────
    ("Adobe",            "adobe",          5,   "external_experienced",    "nyc"),
    ("Adobe ATL",        "adobe",          5,   "external_experienced",    "atlanta"),
    ("Adobe DAL",        "adobe",          5,   "external_experienced",    "dallas"),
    ("Adobe DC",         "adobe",          5,   "external_experienced",    "dc"),
    ("Johnson Controls", "jci",            5,   "JCI",                     "nyc"),
    ("Johnson Controls ATL","jci",         5,   "JCI",                     "atlanta"),
    ("Johnson Controls HOU","jci",         5,   "JCI",                     "houston"),
    ("Johnson Controls DAL","jci",         5,   "JCI",                     "dallas"),
    ("Boeing",           "boeing",         1,   "EXTERNAL_CAREERS",        "dc"),
    ("Boeing DAL",       "boeing",         1,   "EXTERNAL_CAREERS",        "dallas"),
    ("Boeing HOU",       "boeing",         1,   "EXTERNAL_CAREERS",        "houston"),
    ("Marsh McLennan",   "mmc",            1,   "MMC",                     "nyc"),
    ("Marsh McLennan ATL","mmc",           1,   "MMC",                     "atlanta"),
    ("Marsh McLennan DAL","mmc",           1,   "MMC",                     "dallas"),
    ("T-Mobile",         "tmobile",        1,   "External",                "nyc"),
    ("T-Mobile ATL",     "tmobile",        1,   "External",                "atlanta"),
    ("T-Mobile MIA",     "tmobile",        1,   "External",                "miami"),
    ("T-Mobile DAL",     "tmobile",        1,   "External",                "dallas"),
    ("T-Mobile DC",      "tmobile",        1,   "External",                "dc"),
    ("Gartner",          "gartner",        5,   "EXT",                     "nyc"),
    ("Gartner DAL",      "gartner",        5,   "EXT",                     "dallas"),
    ("Gartner DC",       "gartner",        5,   "EXT",                     "dc"),
    ("JLL",              "jll",            1,   "jllcareers",              "nyc"),
    ("JLL ATL",          "jll",            1,   "jllcareers",              "atlanta"),
    ("JLL MIA",          "jll",            1,   "jllcareers",              "miami"),
    ("JLL DAL",          "jll",            1,   "jllcareers",              "dallas"),
    ("JLL HOU",          "jll",            1,   "jllcareers",              "houston"),
    ("JLL DC",           "jll",            1,   "jllcareers",              "dc"),
    ("Equinix",          "equinix",        1,   "External",                "nyc"),
    ("Equinix DAL",      "equinix",        1,   "External",                "dallas"),
    ("Equinix DC",       "equinix",        1,   "External",                "dc"),
    ("Target",           "target",         5,   "targetcareers",           "nyc"),
    ("Target DAL",       "target",         5,   "targetcareers",           "dallas"),
    ("VF Corporation",   "vfc",            5,   "vfc_careers",             "nyc"),
    ("VF Corporation ATL","vfc",           5,   "vfc_careers",             "atlanta"),
    ("Thomson Reuters",  "thomsonreuters", 5,   "External_Career_Site",    "nyc"),
    ("Thomson Reuters DC","thomsonreuters",5,   "External_Career_Site",    "dc"),
    ("Regions Financial","regions",        5,   "Regions_Careers",         "atlanta"),
    ("Regions Financial HOU","regions",    5,   "Regions_Careers",         "houston"),
    ("Regions Financial DAL","regions",    5,   "Regions_Careers",         "dallas"),
    ("PNC Financial",    "pnc",            5,   "External",                "nyc"),
    ("PNC Financial ATL","pnc",            5,   "External",                "atlanta"),
    ("PNC Financial DC", "pnc",            5,   "External",                "dc"),
    ("KeyBank",          "keybank",        5,   "External_Career_Site",    "nyc"),
    ("FIS",              "fis",            5,   "SearchJobs",              "miami"),
    ("FIS ATL",          "fis",            5,   "SearchJobs",              "atlanta"),
    ("FIS DAL",          "fis",            5,   "SearchJobs",              "dallas"),
    ("Broadridge",       "broadridge",     5,   "Careers",                 "nyc"),
]

# (name, greenhouse_token, city)
GREENHOUSE_COMPANIES = [
    # Finance · NYC
    ("KKR",           "kkrcareers",    "nyc"),
    ("Bridgewater",   "bridgewater89", "nyc"),
    ("Point72",       "point72",       "nyc"),
    ("AQR Capital",   "aqr",           "nyc"),
    # Tech · NYC
    ("MongoDB",       "mongodb",       "nyc"),
    ("Datadog",       "datadog",       "nyc"),
    ("Squarespace",   "squarespace",   "nyc"),
    ("DoorDash",      "doordashusa",   "nyc"),
    ("Airbnb",        "airbnb",        "nyc"),
    ("Pinterest",     "pinterest",     "nyc"),
    ("Peloton",       "peloton",       "nyc"),
    # Tech · Atlanta
    ("Cardlytics",    "cardlytics-2",  "atlanta"),
    ("SecureWorks",   "secureworksinc","atlanta"),
    ("Cox Enterprises GH", "coxenterprises", "atlanta"),
    # Finance · NYC (new)
    ("Robinhood",     "robinhood",     "nyc"),
    ("Lone Pine Cap", "lonepinecapital","nyc"),
    # ── Hedge funds / quant · NYC (probed live from droplet 2026-06-18) ────────
    ("ExodusPoint",        "exoduspoint",                "nyc"),
    ("Marshall Wace",      "marshallwace",               "nyc"),
    ("Schonfeld",          "schonfeld",                  "nyc"),
    ("IMC Trading",        "imc",                        "nyc"),
    ("Tower Research",     "towerresearchcapital",       "nyc"),
    ("PDT Partners",       "pdtpartners",                "nyc"),
    ("WorldQuant",         "worldquant",                 "nyc"),
    ("Magnetar Capital",   "magnetar",                   "nyc"),
    ("Capstone",           "capstoneinvestmentadvisors", "nyc"),
    ("Man Group",          "mangroup",                   "nyc"),
    ("Five Rings",         "fiveringsllc",               "nyc"),
    ("Squarepoint",        "squarepointcapital",         "nyc"),
    # Tech · NYC (new)
    ("Stripe",        "stripe",        "nyc"),
    ("Adyen",         "adyen",         "nyc"),
    ("Brex",          "brex",          "nyc"),
    ("Marqeta",       "marqeta",       "nyc"),
    ("Lyft",          "lyft",          "nyc"),
    ("SoFi",          "sofi",          "nyc"),
    ("LinkedIn",      "linkedin",      "nyc"),
    ("Stripe MIA",    "stripe",        "miami"),
    ("Datadog MIA",   "datadog",       "miami"),
    ("MongoDB MIA",   "mongodb",       "miami"),
    # ── Fortune 1000 · NYC ────────────────────────────────────────────────────
    ("Twilio",        "twilio",          "nyc"),
    ("HubSpot",       "hubspotjobs",     "nyc"),
    ("Okta",          "okta",            "nyc"),
    ("Cloudflare",    "cloudflare",      "nyc"),
    ("Coinbase",      "coinbase",        "nyc"),
    ("Toast",         "toast",           "nyc"),
    ("Virtu Financial","virtu",          "nyc"),
    ("NY Times GH",   "thenewyorktimes", "nyc"),
    # ── Fortune 1000 · Miami ──────────────────────────────────────────────────
    ("Chewy",         "chewycom",        "miami"),

    # ── Dallas ────────────────────────────────────────────────────────────────
    ("Stripe DAL",       "stripe",         "dallas"),
    ("MongoDB DAL",      "mongodb",        "dallas"),
    ("Datadog DAL",      "datadog",        "dallas"),
    ("DoorDash DAL",     "doordashusa",    "dallas"),
    # ── Houston ───────────────────────────────────────────────────────────────
    ("Stripe HOU",       "stripe",         "houston"),
    ("MongoDB HOU",      "mongodb",        "houston"),
    ("Datadog HOU",      "datadog",        "houston"),
    # ── Washington DC ─────────────────────────────────────────────────────────
    ("Stripe DC",        "stripe",         "dc"),
    ("MongoDB DC",       "mongodb",        "dc"),
    ("Datadog DC",       "datadog",        "dc"),
    ("Cloudflare DC",    "cloudflare",     "dc"),
    ("Coinbase DC",      "coinbase",       "dc"),
    ("HubSpot DC",       "hubspotjobs",    "dc"),
    ("Okta DC",          "okta",           "dc"),

    # ── Fortune 1000 expansion (verified live 2026-05-18) ─────────────────────
    ("Dropbox",          "dropbox",        "nyc"),
    ("Dropbox DAL",      "dropbox",        "dallas"),
    ("Roblox",           "roblox",         "nyc"),
    ("Chime",            "chime",          "nyc"),
    ("Instacart",        "instacart",      "nyc"),
    ("Instacart DAL",    "instacart",      "dallas"),
    ("Figma",            "figma",          "nyc"),
    ("Discord",          "discord",        "nyc"),
    ("Affirm",           "affirm",         "nyc"),
    ("Reddit",           "reddit",         "nyc"),
    ("Justworks",        "justworks",      "nyc"),
    ("Jump Trading",     "jumptrading",    "nyc"),
    ("Box",              "boxinc",         "nyc"),
    ("Box DAL",          "boxinc",         "dallas"),
    ("Elastic",          "elastic",        "nyc"),
    ("Elastic DC",       "elastic",        "dc"),
    ("GitLab",           "gitlab",         "nyc"),
    ("GitLab DAL",       "gitlab",         "dallas"),
    ("GitLab DC",        "gitlab",         "dc"),
    ("Databricks",       "databricks",     "nyc"),
    ("Databricks ATL",   "databricks",     "atlanta"),
    ("Databricks MIA",   "databricks",     "miami"),
    ("Databricks DAL",   "databricks",     "dallas"),
    ("Databricks HOU",   "databricks",     "houston"),
    ("Databricks DC",    "databricks",     "dc"),
    ("Flexport",         "flexport",       "nyc"),
    ("Flexport DAL",     "flexport",       "dallas"),
    ("Airtable",         "airtable",       "nyc"),
    ("Block",            "block",          "nyc"),
    ("Block ATL",        "block",          "atlanta"),
    ("Block MIA",        "block",          "miami"),
    ("Gemini",           "gemini",         "nyc"),
    ("Gemini MIA",       "gemini",         "miami"),
    ("Samsara",          "samsara",        "nyc"),
    ("Samsara ATL",      "samsara",        "atlanta"),
    ("Samsara DAL",      "samsara",        "dallas"),
    ("Waymo",            "waymo",          "nyc"),
    ("Waymo ATL",        "waymo",          "atlanta"),
    ("Waymo MIA",        "waymo",          "miami"),
    ("Waymo DAL",        "waymo",          "dallas"),
    ("Waymo HOU",        "waymo",          "houston"),
    ("Waymo DC",         "waymo",          "dc"),

    # ── Top companies HQ'd in Los Angeles metro (probed live 2026-06-21) ───────
    ("SpaceX",               "spacex",            "la"),  # Hawthorne
    ("Riot Games",           "riotgames",         "la"),  # West LA
    ("Relativity Space",     "relativity",        "la"),  # Long Beach
    ("The Trade Desk",       "thetradedesk",      "la"),  # Ventura
    ("Scopely",              "scopely",           "la"),  # Culver City
    ("ZipRecruiter",         "ziprecruiter",      "la"),  # Santa Monica
    ("Crunchyroll",          "crunchyroll",       "la"),  # Culver City
    ("Sweetgreen",           "sweetgreen",        "la"),  # Culver City
    ("Faraday Future",       "faradayfuture",     "la"),  # Gardena
    ("Bird",                 "bird",              "la"),  # Santa Monica
    ("GOAT Group",           "goatgroup",         "la"),  # Culver City
    ("Boulevard",            "boulevard",         "la"),  # Los Angeles
    ("Tebra",                "tebra",             "la"),  # Santa Monica
    ("Thrive Market",        "thrivemarket",      "la"),  # Marina del Rey
    ("GumGum",               "gumgum",            "la"),  # Santa Monica
    ("Dr Squatch",           "drsquatch",         "la"),  # Marina del Rey
    ("Boingo Wireless",      "boingo",            "la"),  # Westwood, LA
    ("Cornerstone OnDemand", "cornerstone",       "la"),  # Santa Monica
    ("Liquid Death",         "liquiddeath",       "la"),  # Los Angeles
    ("Dollar Shave Club",    "dollarshaveclub",   "la"),  # Marina del Rey
    ("Mythical Games",       "mythicalgames",     "la"),  # Sherman Oaks
    ("The Honest Company",   "thehonestcompany",  "la"),  # Playa Vista
]

# (name, lever_token, city)
LEVER_COMPANIES = [
    ("Palantir",       "palantir",       "nyc"),
    ("Palantir MIA",   "palantir",       "miami"),
    ("Veeva Systems",  "veeva",          "nyc"),

    # ── Los Angeles metro (Lever, probed live 2026-06-21) ──────────────────────
    ("OpenX",            "openx",          "la"),  # Pasadena
    ("Tala",             "tala",           "la"),  # Santa Monica
    ("System1",          "system1",        "la"),  # Marina del Rey

    ("Palantir DAL",     "palantir",       "dallas"),
    ("Palantir HOU",     "palantir",       "houston"),
    ("Palantir DC",      "palantir",       "dc"),
    ("Veeva Systems DC", "veeva",          "dc"),
]

# Eightfold: (name, domain, base_url, city)
EIGHTFOLD_COMPANIES = [
    ("American Express", "aexp", "https://aexp.eightfold.ai/careers/job", "nyc"),
    ("American Express MIA", "aexp", "https://aexp.eightfold.ai/careers/job", "miami"),
]

# ── $1B+ revenue / unicorn-scale employers (multi-metro) ──────────────────────
# These boards are fetched ONCE each and the metro is inferred per-posting across
# all supported cities (infer_pm_city), instead of one row per company×city. Every
# endpoint below returned HTTP 200 from the production droplet IP on 2026-06-24
# (auto-discovered version+site for Workday; token for Greenhouse/Lever). Tenants
# / tokens already covered by the per-city lists above are intentionally excluded.

# Greenhouse: (name, token)
GREENHOUSE_MULTI = [
    ("10x Genomics", "10xgenomics"),
    ("2U", "2u"),
    ("Amplitude", "amplitude"),
    ("Anthropic", "anthropic"),
    ("Asana", "asana"),
    ("Astranis", "astranis"),
    ("Attentive", "attentive"),
    ("Aurora", "aurorainnovation"),
    ("Bill.com", "billcom"),
    ("Branch", "branchmetrics"),
    ("Braze", "braze"),
    ("C3.ai", "c3iot"),
    ("Calendly", "calendly"),
    ("Calm", "calm"),
    ("Carta", "carta"),
    ("Carvana", "carvana"),
    ("Celonis", "celonis"),
    ("Checkr", "checkr"),
    ("ClassPass", "classpass"),
    ("ClickHouse", "clickhouse"),
    ("Cockroach Labs", "cockroachlabs"),
    ("Compass", "urbancompass"),
    ("Coupang", "coupang"),
    ("Coursera", "coursera"),
    ("Culture Amp", "cultureamp"),
    ("DoubleVerify", "doubleverify"),
    ("Duolingo", "duolingo"),
    ("Faire", "faire"),
    ("FanDuel", "fanduel"),
    ("Fivetran", "fivetran"),
    ("Flatiron Health", "flatironhealth"),
    ("Ginkgo Bioworks", "ginkgobioworks"),
    ("Glossier", "glossier"),
    ("Grafana Labs", "grafanalabs"),
    ("Greenhouse Software", "greenhouse"),
    ("Guild", "guild"),
    ("Gusto", "gusto"),
    ("Imply", "imply"),
    ("Iterable", "iterable"),
    ("JFrog", "jfrog"),
    ("Klaviyo", "klaviyo"),
    ("Komodo Health", "komodohealth"),
    ("Lattice", "lattice"),
    ("Lucid Motors", "lucidmotors"),
    ("Mixpanel", "mixpanel"),
    ("Natera", "natera"),
    ("New Relic", "newrelic"),
    ("Nubank", "nubank"),
    ("Nuro", "nuro"),
    ("Oura", "oura"),
    ("PagerDuty", "pagerduty"),
    ("Planet Labs", "planetlabs"),
    ("Postman", "postman"),
    ("Recursion", "recursionpharmaceuticals"),
    ("SeatGeek", "seatgeek"),
    ("Sigma Computing", "sigmacomputing"),
    ("Smartsheet", "smartsheet"),
    ("Sumo Logic", "sumologic"),
    ("Temporal", "temporaltechnologies"),
    ("Udemy", "udemy"),
    ("Unity Technologies", "unity3d"),
    ("Upstart", "upstart"),
    ("Vercel", "vercel"),
    ("Via", "via"),
    ("Wayve", "wayve"),
    ("Webflow", "webflow"),
]

# Lever: (name, token)
LEVER_MULTI = [
    ("Alloy", "alloy"),
    ("Ro", "ro"),
    ("Spotify", "spotify"),
]

# Workday: (name, tenant, ver, site)
WORKDAY_MULTI = [
    # Fortune 1000 Houston-HQ employers (verified HTTP 200 from the droplet
    # 2026-07-04; site names discovered via landing-page redirects). Listed as
    # multi-metro so a KBR program-manager role in DC or NYC surfaces too —
    # the posting's own location decides the metro, not the HQ.
    ("Plains All American",  "plains",              1, "plains"),
    ("Corebridge Financial", "corebridgefinancial", 1, "corebridgefinancial"),
    ("Westlake",             "westlake",            1, "westlake"),
    ("KBR",                  "kbr",                 5, "kbr_careers"),
    ("Chord Energy",         "chordenergy",         1, "External"),
    ("Service Corp Intl",    "sci",                 5, "sci"),
    ("Stewart Title",        "stewart",             1, "External"),
    ("Occidental",           "oxy",                 5, "Corporate"),
    ("Comfort Systems USA",  "comfortsystemsusa",   1, "Corpcareers"),
    ("DNOW",                 "distributionnow",     5, "DNOW_Careers"),
    ("Academy Sports", "academy", 1, "Careers"),
    ("Amgen", "amgen", 1, "Careers"),
    ("Analog Devices", "analogdevices", 1, "External"),
    ("Applied Materials", "amat", 1, "External"),
    ("Aptiv", "aptiv", 5, "Aptiv_Careers"),
    ("Avnet", "avnet", 1, "External"),
    ("BorgWarner", "borgwarner", 5, "Borgwarner_Careers"),
    ("Burlington", "burlington", 5, "BurlingtonCareers"),
    ("CNA Financial", "cna", 1, "Cna_Careers"),
    ("Centene", "centene", 5, "Centene_External"),
    ("Chewy", "chewy", 5, "External"),
    ("Chipotle", "chipotle", 5, "ChipotleCareers"),
    ("Choice Hotels", "choicehotels", 5, "External"),
    ("Devon Energy", "devonenergy", 5, "Careers"),
    ("Diageo", "diageo", 3, "Diageo_Careers"),
    ("Ecolab", "ecolab", 1, "Ecolab_External"),
    ("Edwards Lifesciences", "edwards", 5, "EdwardsCareers"),
    ("Everest", "everestre", 5, "External"),
    ("Expedia", "expediagroup", 5, "careers"),
    ("Flex", "flextronics", 1, "Careers"),
    ("Gilead", "gilead", 1, "GileadCareers"),
    ("Goodyear", "goodyear", 1, "GoodyearCareers"),
    ("Illinois Tool Works", "itw", 5, "External"),
    ("Jabil", "jabil", 5, "Jabil_Careers"),
    ("LPL Financial", "lplfinancial", 1, "External"),
    ("Labcorp", "labcorp", 1, "External"),
    ("Las Vegas Sands", "sands", 1, "Sands_Careers"),
    ("Marathon Petroleum", "mpc", 1, "MpcCareers"),
    ("Mars", "mars", 3, "External"),
    ("Marvell", "marvell", 1, "MarvellCareers"),
    ("Medtronic", "medtronic", 1, "MedtronicCareers"),
    ("Micron", "micron", 1, "External"),
    ("Motorola Solutions", "motorolasolutions", 5, "Careers"),
    ("NXP", "nxp", 3, "Careers"),
    ("Old Dominion", "odfl", 1, "Odfl_Careers"),
    ("PPG", "ppg", 5, "Ppg_Careers"),
    ("Qualcomm", "qualcomm", 12, "External"),
    ("Qualys", "qualys", 5, "Careers"),
    ("Raymond James", "raymondjames", 1, "RaymondjamesCareers"),
    ("Regeneron", "regeneron", 1, "Careers"),
    ("RingCentral", "ringcentral", 1, "Ringcentral_Careers"),
    ("Stryker", "stryker", 1, "StrykerCareers"),
    # TJX removed 2026-07-04 — owner excluded the company site-wide
    # (see EXCLUDE_COMPANIES in app/matching.py).
    ("Tapestry", "tapestry", 108, "Tapestry_Careers"),
    ("Thermo Fisher", "thermofisher", 5, "ThermofisherCareers"),
    ("Trimble", "trimble", 1, "TrimbleCareers"),
    ("Unisys", "unisys", 5, "External"),
    ("Unum", "unum", 1, "External"),
    ("Walmart", "walmart", 5, "External"),
    ("Williams", "williams", 5, "External"),
    ("Xcel Energy", "xcelenergy", 1, "External"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def load_store():
    if STORE_FILE.exists():
        return json.loads(STORE_FILE.read_text())
    return []


def save_store(store):
    STORE_FILE.write_text(json.dumps(store, indent=2))


def save_shared_jobs(shared_jobs):
    SHARED_JOBS_FILE.write_text(json.dumps(shared_jobs, indent=2))


def purge_old_store(store):
    cutoff = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
    kept = []
    for job in store:
        try:
            found_at = datetime.fromisoformat(job.get("found_at", ""))
            if found_at.tzinfo is None:
                found_at = found_at.replace(tzinfo=timezone.utc)
            if found_at >= cutoff:
                kept.append(job)
        except Exception:
            kept.append(job)
    return kept


def is_vp(title):
    t = title.lower()
    if any(re.search(p, t) for p in EXCLUDE_SENIORITY):
        return False
    return any(re.search(p, t) for p in VP_TERMS)


def is_senior(title):
    t = title.lower()
    return any(re.search(p, t) for p in SENIOR_TERMS)


def level_ok(title, city):
    """VP or Senior accepted in every city (city kept for signature compatibility)."""
    return is_vp(title) or is_senior(title)


def is_target_role(title):
    t = title.lower()
    return any(r in t for r in TARGET_ROLES)


def is_nyc(text):
    t = text.lower()
    return any(loc in t for loc in NYC_LOCS)


def is_atlanta(text):
    t = text.lower()
    return any(loc in t for loc in ATLANTA_LOCS)


def is_miami(text):
    t = text.lower()
    return any(loc in t for loc in MIAMI_LOCS)


def is_dallas(text):
    t = text.lower()
    return any(loc in t for loc in DALLAS_LOCS)


def is_houston(text):
    t = text.lower()
    return any(loc in t for loc in HOUSTON_LOCS)


def is_dc(text):
    t = text.lower()
    return any(loc in t for loc in DC_LOCS)


def is_la(text):
    t = text.lower()
    return any(loc in t for loc in LA_LOCS)


def location_ok(text, city):
    if city == "nyc":
        return is_nyc(text)
    if city == "atlanta":
        return is_atlanta(text)
    if city == "miami":
        return is_miami(text)
    if city == "dallas":
        return is_dallas(text)
    if city == "houston":
        return is_houston(text)
    if city == "dc":
        return is_dc(text)
    if city == "la":
        return is_la(text)
    return False


# Metros covered by the multi-metro ($1B+) scrapers; first match wins, so the
# order matters: the specific-named metros are checked BEFORE Dallas, whose
# pattern list intentionally includes broad Texas catch-alls (", tx", "texas")
# for per-city use. Without this ordering "Houston, TX" would match Dallas's
# ", tx", and "Arlington, VA" would match Dallas's bare "arlington" before DC.
PM_METROS = ("nyc", "miami", "atlanta", "la", "dc", "houston", "dallas")

def infer_pm_city(text):
    """Return the first supported metro whose pattern matches `text`, else None."""
    for c in PM_METROS:
        if location_ok(text, c):
            return c
    return None


# City labels ("Boise, ID") that users picked in the state-grouped selector,
# beyond the built-in metros. Loaded from the app DB at run start; multi-metro
# postings in these cities are kept with city="extra" and matched app-side
# against the raw location string.
ACTIVE_EXTRA_CITIES: list = []

_STATE_NAMES_LOWER = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas",
    "ca": "california", "co": "colorado", "ct": "connecticut", "de": "delaware",
    "dc": "district of columbia", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana",
    "ia": "iowa", "ks": "kansas", "ky": "kentucky", "la": "louisiana",
    "me": "maine", "md": "maryland", "ma": "massachusetts", "mi": "michigan",
    "mn": "minnesota", "ms": "mississippi", "mo": "missouri", "mt": "montana",
    "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey",
    "nm": "new mexico", "ny": "new york", "nc": "north carolina",
    "nd": "north dakota", "oh": "ohio", "ok": "oklahoma", "or": "oregon",
    "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina",
    "sd": "south dakota", "tn": "tennessee", "tx": "texas", "ut": "utah",
    "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming",
}


def load_active_extra_cities():
    """Distinct PM-search city labels beyond the built-in metro labels."""
    import sqlite3
    labels = set()
    db_path = Path(__file__).resolve().parent / "jordansjobfinder.db"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        for (cities_json,) in conn.execute(
            "SELECT cities FROM saved_searches WHERE vertical='pm'"
        ):
            for label in json.loads(cities_json or "[]"):
                labels.add(label)
        conn.close()
    except Exception as exc:
        log(f"  active-extra-cities load failed: {exc}")
        return []
    return sorted(labels - set(CITY_LABELS.values()))


def location_matches_extra(location):
    """Whether a raw location string sits in any user-selected extra city.
    City name AND a state signal must both appear (mirrors
    app/matching.location_matches_city)."""
    loc = (location or "").lower()
    if not loc:
        return False
    for label in ACTIVE_EXTRA_CITIES:
        if ", " not in label:
            continue
        city, st = label.rsplit(", ", 1)
        st_lower = st.lower()
        if city.lower() not in loc:
            continue
        if (
            f", {st_lower}" in loc
            or f" {st_lower} " in f"{loc} "
            or _STATE_NAMES_LOWER.get(st_lower, chr(0)) in loc
        ):
            return True
    return False


def infer_pm_city_or_extra(text):
    """Metro slug, "extra" for a user-selected city, or None."""
    city = infer_pm_city(text)
    if city:
        return city
    if ACTIVE_EXTRA_CITIES and location_matches_extra(text):
        return "extra"
    return None


def is_recent_rfc(pub_date_str):
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
        return pub_dt >= cutoff
    except Exception:
        return False


def is_recent_iso(date_str):
    if not date_str:
        return False
    try:
        for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                ds = date_str.strip()
                if fmt == "%Y-%m-%dT%H:%M:%S%z":
                    dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
                    cutoff = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
                    return dt.replace(tzinfo=timezone.utc) >= cutoff
                dt = datetime.strptime(ds[:10], "%Y-%m-%d") if fmt == "%Y-%m-%d" else datetime.strptime(ds, fmt)
                cutoff = datetime.now() - timedelta(days=VALID_POST_DAYS)
                return dt >= cutoff
            except ValueError:
                continue
    except Exception:
        pass
    return False


def salary_ok(salary_text):
    result = parse_salary(salary_text)
    if not result:
        return False
    _, max_sal = result
    return max_sal >= MIN_SALARY


def normalize_title(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def is_tech(description):
    desc = description.lower()
    return sum(1 for kw in TECH_SIGNALS if kw in desc) >= TECH_THRESHOLD


def normalize_posted_date(value):
    value = (value or "").strip()
    if not value:
        return ""

    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", value)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d").strftime("%B %d, %Y")
        except ValueError:
            pass

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value.replace(".", ""), fmt).strftime("%B %d, %Y")
        except ValueError:
            continue

    rel_match = re.search(r"\b(\d+)\s+(day|hour|minute)s?\s+ago\b", value, re.I)
    if rel_match:
        qty = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        delta_args = {f"{unit}s": qty}
        dt = datetime.now() - timedelta(**delta_args)
        return dt.strftime("%B %d, %Y")

    # Strip common prefixes like "Posted today" → "today"
    lower = value.lower()
    for prefix in ("posted ", "date posted: ", "published "):
        if lower.startswith(prefix):
            lower = lower[len(prefix):]
            break

    if lower == "today":
        return datetime.now().strftime("%B %d, %Y")
    if lower == "yesterday":
        return (datetime.now() - timedelta(days=1)).strftime("%B %d, %Y")

    return value


def extract_posted_date(soup, full_text):
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for key in ("datePosted", "datePublished", "dateCreated", "uploadDate"):
                    if item.get(key):
                        normalized = normalize_posted_date(str(item[key]))
                        if normalized:
                            return normalized
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)

    for meta_selector in [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "publish-date"}),
        ("meta", {"name": "date"}),
        ("meta", {"name": "dc.date"}),
        ("meta", {"itemprop": "datePosted"}),
    ]:
        tag = soup.find(*meta_selector)
        if tag and tag.get("content"):
            normalized = normalize_posted_date(tag["content"])
            if normalized:
                return normalized

    patterns = [
        r"(?:posted|date posted|posted on|job posted|published|publication date|updated|last updated)\s*[:\-]?\s*([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})",
        r"(?:posted|date posted|posted on|job posted|published|publication date|updated|last updated)\s*[:\-]?\s*(20\d{2}-\d{2}-\d{2})",
        r"(?:posted|date posted|posted on|job posted|published|publication date|updated|last updated)\s*[:\-]?\s*(today|yesterday|\d+\s+(?:day|hour|minute)s?\s+ago)",
    ]
    for pattern in patterns:
        match = re.search(pattern, full_text, re.I)
        if match:
            normalized = normalize_posted_date(match.group(1))
            if normalized:
                return normalized

    return "Unknown"


def format_posted_label(job):
    posted = job.get("posted", "").strip()
    if posted and posted != "Unknown":
        return f"Posted: {posted}"

    found_at = job.get("found_at", "").strip()
    if found_at:
        try:
            found_dt = datetime.fromisoformat(found_at.replace("Z", "+00:00"))
            return f"Found: {found_dt.strftime('%B %d, %Y')}"
        except ValueError:
            pass

    return "Posted: Unknown"


def make_job(title, url, company, city, salary="", posted="Unknown", location="", source="unknown"):
    return dict(title=title, url=url, company=company, city=city,
                salary=salary, posted=posted, location=location, source=source)


# ── Fortune 1000 Houston extra-ATS employers (Oracle Cloud / iCIMS) ──────────
# Houston-HQ Fortune 1000 companies whose boards aren't on Workday/Greenhouse/
# Lever. Scraped through scraper_ats_extra's platform functions with PM-scope
# filters; the candidates then flow through the same detail-page enrichment
# (description / salary / tech-focus) as every other source. Endpoints
# verified HTTP 200 from the droplet 2026-07-04. Still unreachable: Enterprise
# Products (legacy Taleo), CenterPoint + Murphy Oil (hosted SuccessFactors
# variant), Crown Castle (UKG), APA + Crescent Energy (no public ATS API).
HOUSTON_EXTRA_ORACLE = [
    ("Cheniere Energy", "hcgi.fa.us2.oraclecloud.com",              "CX_2"),
    ("NOV",             "egay.fa.us6.oraclecloud.com",              "CX_2001"),
    ("Patterson-UTI",   "fa-elpm-saasfaprod1.fa.ocs.oraclecloud.com", "CX"),
    ("Oceaneering",     "ebfr.fa.us2.oraclecloud.com",              "CX_3001"),
]
HOUSTON_EXTRA_ICIMS = [
    ("Quanta Services",    "careers-quanta"),
    ("Group 1 Automotive", "group1auto"),
    ("Kinder Morgan",      "careers-kindermorgan"),
    ("Kirby",              "kirbycorp"),
]


def collect_houston_extra():
    """PM-scope candidates from the Houston Oracle/iCIMS employers above."""
    from types import SimpleNamespace

    from scraper_ats_extra import _safe, scrape_icims, scrape_oracle

    def _recent(posted_dt):
        if posted_dt is None:
            return False
        return (datetime.now(timezone.utc) - posted_dt).days <= VALID_POST_DAYS

    ctx = SimpleNamespace(
        title_filter=lambda t: is_target_role(t) and level_ok(t, "houston"),
        infer_city=infer_pm_city,
        within_recency=_recent,
        make_job=lambda **kw: make_job(
            title=kw["title"], url=kw["url"], company=kw["company"],
            city=kw["city"], posted=kw.get("posted_label") or "Unknown",
            location=kw.get("location", ""), source=kw["source"],
        ),
        source=lambda platform: f"{platform}-pm",
    )
    jobs = []
    for name, host, site in HOUSTON_EXTRA_ORACLE:
        log(f"  [{name}] Oracle...")
        jobs += _safe(name, scrape_oracle, ctx, name, host, site)
    for name, subdomain in HOUSTON_EXTRA_ICIMS:
        log(f"  [{name}] iCIMS...")
        jobs += _safe(name, scrape_icims, ctx, name, subdomain)
    return jobs


def city_display(city, location):
    if location:
        return location
    return CITY_LABELS.get(city, "")


def parse_salary_bounds(salary_text):
    parsed = parse_salary(salary_text or "")
    if not parsed:
        return None, None
    return parsed


def parse_posted_datetime_from_label(posted):
    posted = (posted or "").strip()
    if not posted or posted == "Unknown":
        return None

    if posted.lower() == "posted today" or posted.lower() == "today":
        return datetime.now(timezone.utc)
    if posted.lower() == "yesterday":
        return datetime.now(timezone.utc) - timedelta(days=1)

    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(posted, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # ISO-8601 with a time/offset, e.g. 2026-02-11T03:57:07Z or ...-04:00.
    # Without this, ATS feeds that hand back a full timestamp leave posted_at
    # NULL while posted_label keeps the (often stale) date, so the recency
    # filter falls back to found_at and an old job looks fresh forever.
    try:
        dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def extract_experience_bounds(text):
    parsed = parse_experience_years(text)
    return parsed.min_years, parsed.max_years


def normalize_shared_job(job, description=""):
    salary_min, salary_max = parse_salary_bounds(job.get("salary") or description)
    salary_bounds = (salary_min, salary_max) if salary_min is not None else None
    if salary_bounds and salary_bounds[1] < MIN_SALARY:
        salary_bounds = None
        salary_min, salary_max = None, None
    salary_label = job.get("salary", "")
    if salary_bounds and (not salary_label or salary_label == "See posting"):
        salary_label = format_salary_label(salary_bounds)
    exp_min, exp_max = extract_experience_bounds(f"{job.get('title', '')} {description}")
    posted_label = job.get("posted", "Unknown")
    posted_at = parse_posted_datetime_from_label(posted_label)
    found_at_raw = job.get("found_at")
    found_at = None
    if found_at_raw:
        try:
            found_at = datetime.fromisoformat(found_at_raw)
        except ValueError:
            found_at = None

    return {
        "source": job.get("source", "jordansjobfinder-shared"),
        "company": job.get("company", ""),
        "title": job.get("title", ""),
        "normalized_title": normalize_title(job.get("title", "")),
        "url": job.get("url", ""),
        "city": job.get("city", ""),
        "location": city_display(job.get("city", ""), job.get("location", "")),
        "description": description,
        "salary_label": salary_label or "See posting",
        "salary_min": salary_min,
        "salary_max": salary_max,
        "posted_label": posted_label,
        "posted_at": posted_at.isoformat() if posted_at else None,
        "experience_min": exp_min,
        "experience_max": exp_max,
        "is_technical": True,
        "found_at": found_at.isoformat() if found_at else datetime.now(timezone.utc).isoformat(),
    }


# ── Playwright detail fetcher ──────────────────────────────────────────────────

def fetch_detail(page, url):
    """Return (salary_text, full_text, posted_str)."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2000)
        # Accept cookie consent if present (Workday / other sites)
        for sel in ["button[data-automation-id='acceptAllButton']",
                    "button:has-text('Accept')", "button:has-text('Accept Cookies')",
                    "#onetrust-accept-btn-handler"]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                pass
    except Exception:
        return "", "", ""

    html = page.content()
    soup      = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(separator=" ", strip=True)

    salary = ""
    salary_sources = [full_text, html]
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.get_text(" ", strip=True)
        if raw:
            salary_sources.append(raw)

    for source_text in salary_sources:
        parsed_salary = parse_salary(source_text)
        if not parsed_salary:
            continue
        low, high = parsed_salary
        salary = f"${low:,.0f}" if low == high else f"${low:,.0f} – ${high:,.0f}"
        break

    posted = extract_posted_date(soup, full_text)

    return salary, full_text, posted


def fetch_workday_detail(url):
    try:
        resp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=20)
        if resp.status_code != 200:
            return "", "", ""
    except Exception:
        return "", "", ""

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(separator=" ", strip=True)

    salary = ""
    salary_sources = [full_text, html]
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.get_text(" ", strip=True)
        if raw:
            salary_sources.append(raw)

    for source_text in salary_sources:
        parsed_salary = parse_salary(source_text)
        if not parsed_salary:
            continue
        salary = format_salary_label(parsed_salary)
        break

    posted = extract_posted_date(soup, full_text)
    return salary, full_text, posted


# ══════════════════════════════════════════════════════════════════════════════
#  SCRAPERS
# ══════════════════════════════════════════════════════════════════════════════

# ── Citigroup — TalentBrew RSS ─────────────────────────────────────────────────

def scrape_citi():
    log("  [Citigroup] Fetching RSS feed...")
    try:
        req = urllib.request.Request(
            "https://jobs.citi.com/rss/jobs",
            headers={"User-Agent": HEADERS["User-Agent"]}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        log(f"    Error: {e}")
        return []

    candidates = []
    for item in root.findall(".//item"):
        title    = item.findtext("title") or ""
        url      = item.findtext("link")  or ""
        pub_date = item.findtext("pubDate") or ""
        if not (is_nyc(title) and is_target_role(title) and is_vp(title)
                and is_recent_rfc(pub_date)):
            continue
        candidates.append(make_job(
            title=title.split(" - (")[0].strip(),
            url=url, company="Citigroup", city="nyc", posted=pub_date, source="talentbrew-rss"
        ))
    log(f"  [Citigroup] {len(candidates)} candidate(s)")
    return candidates


# ── Generic Workday API ────────────────────────────────────────────────────────

def scrape_workday_company(name, tenant, wd_ver, site, city):
    api = (f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com"
           f"/wday/cxs/{tenant}/{site}/jobs")
    candidates = []

    for term in ["product manager", "program manager"]:
        offset = 0
        while True:
            try:
                resp = requests.post(api,
                    json={"appliedFacets": {}, "limit": 20,
                          "offset": offset, "searchText": term},
                    headers={"Content-Type": "application/json",
                             "User-Agent": HEADERS["User-Agent"]},
                    timeout=15)
                if resp.status_code != 200:
                    break
                data = resp.json()
            except Exception as e:
                log(f"    [{name}] Error: {e}")
                break

            postings = data.get("jobPostings", [])
            total    = data.get("total", 0)

            for job in postings:
                title    = job.get("title", "")
                ext_path = job.get("externalPath", "")
                location = job.get("locationsText", "")
                posted   = job.get("postedOn", "")

                if not (is_target_role(title) and level_ok(title, city)):
                    continue
                loc_check = location or title
                if not location_ok(loc_check, city):
                    continue

                url = (f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com"
                       f"/en-US/{site}{ext_path}")
                candidates.append(make_job(
                    title=title, url=url, company=name, city=city,
                    posted=posted, location=location, source="workday"
                ))

            offset += 20
            if offset >= total or not postings:
                break
            time.sleep(0.5)

    return candidates


# ── Generic Greenhouse API ─────────────────────────────────────────────────────

def scrape_greenhouse_company(name, token, city):
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log(f"    [{name}] Greenhouse {resp.status_code}")
            return []
        jobs = resp.json().get("jobs", [])
    except Exception as e:
        log(f"    [{name}] Error: {e}")
        return []

    candidates = []
    for job in jobs:
        title    = job.get("title", "")
        location = job.get("location", {}).get("name", "")
        job_url  = job.get("absolute_url", "")
        updated  = job.get("updated_at", "")[:10]
        content  = BeautifulSoup(job.get("content", ""), "html.parser").get_text(" ")

        if not (is_target_role(title) and level_ok(title, city)):
            continue
        if not location_ok(location or content[:500], city):
            continue
        if updated and not is_recent_iso(updated):
            continue

        candidates.append(make_job(
            title=title, url=job_url, company=name, city=city,
            posted=updated, location=location, source="greenhouse"
        ))

    return candidates


# ── Generic Lever API ──────────────────────────────────────────────────────────

def scrape_lever_company(name, token, city):
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log(f"    [{name}] Lever {resp.status_code}")
            return []
        postings = resp.json()
    except Exception as e:
        log(f"    [{name}] Error: {e}")
        return []

    candidates = []
    for job in postings:
        title     = job.get("text", "")
        location  = job.get("categories", {}).get("location", "")
        job_url   = job.get("hostedUrl", "")
        created   = job.get("createdAt", 0)
        desc_text = job.get("descriptionPlain", "") or ""

        if not (is_target_role(title) and level_ok(title, city)):
            continue
        if not location_ok(location or desc_text[:500], city):
            continue
        # created is Unix ms
        try:
            post_dt = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            cutoff  = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
            if post_dt < cutoff:
                continue
        except Exception:
            pass

        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if created else ""
        candidates.append(make_job(
            title=title, url=job_url, company=name, city=city,
            posted=posted, location=location, source="lever"
        ))

    return candidates


# ── Multi-metro variants ($1B+ employers) ──────────────────────────────────────
# Fetch each board once; infer the metro per posting across every supported city
# (infer_pm_city) rather than re-fetching once per city. Used for GREENHOUSE_MULTI
# / LEVER_MULTI / WORKDAY_MULTI.

def scrape_greenhouse_multi(name, token):
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log(f"    [{name}] Greenhouse {resp.status_code}")
            return []
        jobs = resp.json().get("jobs", [])
    except Exception as e:
        log(f"    [{name}] Error: {e}")
        return []

    candidates = []
    for job in jobs:
        title    = job.get("title", "")
        location = job.get("location", {}).get("name", "")
        job_url  = job.get("absolute_url", "")
        updated  = job.get("updated_at", "")[:10]
        content  = BeautifulSoup(job.get("content", ""), "html.parser").get_text(" ")

        if not is_target_role(title):
            continue
        city = infer_pm_city_or_extra(location or content[:600])
        if not city or not level_ok(title, city):
            continue
        if updated and not is_recent_iso(updated):
            continue

        candidates.append(make_job(
            title=title, url=job_url, company=name, city=city,
            posted=updated, location=location, source="greenhouse"
        ))

    return candidates


def scrape_lever_multi(name, token):
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log(f"    [{name}] Lever {resp.status_code}")
            return []
        postings = resp.json()
    except Exception as e:
        log(f"    [{name}] Error: {e}")
        return []

    candidates = []
    for job in postings:
        title     = job.get("text", "")
        location  = job.get("categories", {}).get("location", "")
        job_url   = job.get("hostedUrl", "")
        created   = job.get("createdAt", 0)
        desc_text = job.get("descriptionPlain", "") or ""

        if not is_target_role(title):
            continue
        city = infer_pm_city_or_extra(location or desc_text[:600])
        if not city or not level_ok(title, city):
            continue
        try:
            post_dt = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            cutoff  = datetime.now(timezone.utc) - timedelta(days=VALID_POST_DAYS)
            if post_dt < cutoff:
                continue
        except Exception:
            pass

        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if created else ""
        candidates.append(make_job(
            title=title, url=job_url, company=name, city=city,
            posted=posted, location=location, source="lever"
        ))

    return candidates


def scrape_workday_multi(name, tenant, wd_ver, site):
    api = (f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com"
           f"/wday/cxs/{tenant}/{site}/jobs")
    candidates = []

    for term in ["product manager", "program manager"]:
        offset = 0
        while True:
            try:
                resp = requests.post(api,
                    json={"appliedFacets": {}, "limit": 20,
                          "offset": offset, "searchText": term},
                    headers={"Content-Type": "application/json",
                             "User-Agent": HEADERS["User-Agent"]},
                    timeout=15)
                if resp.status_code != 200:
                    break
                data = resp.json()
            except Exception as e:
                log(f"    [{name}] Error: {e}")
                break

            postings = data.get("jobPostings", [])
            total    = data.get("total", 0)

            for job in postings:
                title    = job.get("title", "")
                ext_path = job.get("externalPath", "")
                location = job.get("locationsText", "")
                posted   = job.get("postedOn", "")

                if not is_target_role(title):
                    continue
                city = infer_pm_city_or_extra(location or title)
                if not city or not level_ok(title, city):
                    continue

                url = (f"https://{tenant}.wd{wd_ver}.myworkdayjobs.com"
                       f"/en-US/{site}{ext_path}")
                candidates.append(make_job(
                    title=title, url=url, company=name, city=city,
                    posted=posted, location=location, source="workday"
                ))

            offset += 20
            if offset >= total or not postings:
                break
            time.sleep(0.5)

    return candidates


# ── Generic Eightfold API ──────────────────────────────────────────────────────

def scrape_eightfold_company(name, domain, base_url, city):
    loc_query = CITY_SEARCH[city]
    candidates = []

    for term in ["product manager", "program manager"]:
        try:
            resp = requests.get(
                f"https://{domain}.eightfold.ai/api/apply/v2/jobs",
                params={"domain": f"{domain}.com", "query": term,
                        "location": loc_query, "count": 50, "page": 1},
                headers=HEADERS, timeout=15)
            jobs = resp.json().get("positions", [])
        except Exception as e:
            log(f"    [{name}] Error: {e}")
            continue

        for job in jobs:
            title    = job.get("name", "")
            job_id   = job.get("id", "")
            location = job.get("location", "")
            t_create = job.get("t_create")
            try:
                posted = datetime.fromtimestamp(int(t_create), tz=timezone.utc).strftime("%Y-%m-%d") if t_create else ""
            except Exception:
                posted = ""

            if not (is_target_role(title) and level_ok(title, city)):
                continue
            if not location_ok(location, city):
                continue
            if posted and not is_recent_iso(posted):
                continue

            url = f"{base_url}/{job_id}"
            candidates.append(make_job(
                title=title, url=url, company=name, city=city,
                posted=posted, location=location, source="eightfold"
            ))
        time.sleep(1)

    return candidates


# ── JPMorgan Chase — Playwright ────────────────────────────────────────────────

def scrape_jpmorgan(page):
    log("  [JPMorgan Chase] Playwright...")
    candidates = []
    for term in ["product manager", "program manager"]:
        url = (f"https://careers.jpmorgan.com/US/en/jobs"
               f"?search={urllib.parse.quote(term)}&location=New+York&lob=Technology")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(5000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for card in soup.select("[data-job-id], .job-listing, [class*='job-card'], [class*='requisition']"):
            title_el = card.find("h2") or card.find("h3") or card.find(class_=re.compile(r"title|heading", re.I))
            link_el  = card.find("a", href=True)
            loc_el   = card.find(class_=re.compile(r"location|city", re.I))
            if not title_el:
                continue
            title    = title_el.get_text(strip=True)
            location = loc_el.get_text(strip=True) if loc_el else ""
            href     = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = "https://careers.jpmorgan.com" + href
            if not (is_target_role(title) and is_vp(title) and is_nyc(location or title)):
                continue
            candidates.append(make_job(title=title, url=href,
                                       company="JPMorgan Chase", city="nyc", location=location, source="playwright-jpmc"))
        time.sleep(2)
    log(f"  [JPMorgan Chase] {len(candidates)} candidate(s)")
    return candidates


# ── Goldman Sachs — Playwright ─────────────────────────────────────────────────

def scrape_goldman(page):
    log("  [Goldman Sachs] Playwright...")
    candidates = []
    for term in ["product manager", "program manager"]:
        url = f"https://higher.gs.com/roles?query={urllib.parse.quote(term)}&region=Americas"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(4000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for link_el in soup.select("a[href*='/roles/']"):
            full_text = link_el.get_text(separator=" ", strip=True)
            href      = link_el["href"]
            if not href.startswith("http"):
                href = "https://higher.gs.com" + href

            title    = full_text
            location = ""
            for loc_kw in ["New York", "Jersey City", "NYC"]:
                if loc_kw in full_text:
                    idx      = full_text.index(loc_kw)
                    title    = full_text[:idx].strip().rstrip("-,·").strip()
                    location = full_text[idx:]
                    break

            if not (is_target_role(title) and is_vp(title)):
                continue
            if location and not is_nyc(location):
                continue
            if not location and not is_nyc(full_text):
                continue

            candidates.append(make_job(title=title, url=href,
                                       company="Goldman Sachs", city="nyc",
                                       location=location or "New York, NY", source="playwright-goldman"))
        time.sleep(2)
    log(f"  [Goldman Sachs] {len(candidates)} candidate(s)")
    return candidates


# ── MetLife — Playwright ───────────────────────────────────────────────────────

def scrape_metlife(page):
    log("  [MetLife] Playwright...")
    candidates = []
    for term in ["product manager", "program manager"]:
        url = f"https://www.metlifecareers.com/en_US/ml/SearchJobs/{urllib.parse.quote(term)}?3_118_3=8491"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(3000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for card in soup.select("[class*='job'], [class*='position'], li.result"):
            title_el = card.find("h2") or card.find("h3") or card.find(class_=re.compile(r"title", re.I))
            link_el  = card.find("a", href=True)
            loc_el   = card.find(class_=re.compile(r"location", re.I))
            if not title_el:
                continue
            title    = title_el.get_text(strip=True)
            location = loc_el.get_text(strip=True) if loc_el else ""
            href     = link_el["href"] if link_el else ""
            if href and not href.startswith("http"):
                href = "https://www.metlifecareers.com" + href
            if not (is_nyc(location) and is_target_role(title) and is_vp(title)):
                continue
            candidates.append(make_job(title=title, url=href,
                                       company="MetLife", city="nyc", location=location, source="playwright-metlife"))
        time.sleep(1)
    log(f"  [MetLife] {len(candidates)} candidate(s)")
    return candidates


# ── Meta — Playwright ─────────────────────────────────────────────────────────

def scrape_meta(page, city="nyc"):
    log(f"  [Meta] Playwright ({city})...")
    candidates = []
    for term in ["product manager", "program manager"]:
        url = (f"https://www.metacareers.com/jobs?q={urllib.parse.quote(term)}"
               f"&offices[]={urllib.parse.quote(CITY_LABELS[city])}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(5000)
        except PWTimeout:
            continue

        soup = BeautifulSoup(page.content(), "html.parser")
        for card in soup.select("[class*='_job'], [data-testid*='job'], a[href*='/jobs/']"):
            title_el = card.find(class_=re.compile(r"title|heading", re.I)) or card.find("span")
            link_el  = card if card.name == "a" else card.find("a", href=True)
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href  = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = "https://www.metacareers.com" + href
            if not (is_target_role(title) and level_ok(title, city)):
                continue
            candidates.append(make_job(title=title, url=href,
                                       company="Meta", city=city,
                                       location=CITY_LABELS[city], source="playwright-meta"))
        time.sleep(2)
    log(f"  [Meta] {len(candidates)} candidate(s)")
    return candidates


# ── Amazon — JSON API ─────────────────────────────────────────────────────────

def scrape_amazon(city="nyc"):
    log(f"  [Amazon] API ({city})...")
    candidates = []
    loc = AMAZON_LOCATIONS[city]

    for term in ["product manager", "program manager"]:
        try:
            resp = requests.get(
                "https://www.amazon.jobs/en/search.json",
                params={"keywords": term, "normalized_location[]": loc,
                        "result_limit": 50, "offset": 0},
                headers={"User-Agent": HEADERS["User-Agent"],
                         "Accept": "application/json"},
                timeout=15)
            if resp.status_code != 200:
                continue
            jobs = resp.json().get("jobs", [])
        except Exception as e:
            log(f"    [Amazon] Error: {e}")
            continue

        for job in jobs:
            title    = job.get("title", "")
            location = job.get("location", "")
            job_url  = "https://www.amazon.jobs" + job.get("job_path", "")
            updated  = job.get("updated_time", "")[:10]

            if not (is_target_role(title) and level_ok(title, city)):
                continue
            if not location_ok(location, city):
                continue
            if updated and not is_recent_iso(updated):
                continue

            candidates.append(make_job(
                title=title, url=job_url, company="Amazon",
                city=city, posted=updated, location=location, source="amazon-api"
            ))
        time.sleep(1)

    log(f"  [Amazon] {len(candidates)} candidate(s)")
    return candidates


# ── Built In NYC — HTML listing scrape ────────────────────────────────────────

BUILTIN_NYC_BASE = "https://www.builtinnyc.com/jobs"
BUILTIN_RECENCY_HOURS = 24
BUILTIN_MAX_PAGES = 8
BUILTIN_PARAMS = {
    "search": "product",
    "daysSinceUpdated": "1",
    "city": "New York City",
    "state": "New York",
    "country": "USA",
    "allLocations": "true",
}


def parse_builtin_posted(card_text):
    """Return a tz-aware datetime from BuiltIn's relative posted label, or None."""
    if not card_text:
        return None
    t = card_text.lower()
    if "just now" in t or "moments ago" in t:
        return datetime.now(timezone.utc)
    m = re.search(r"(\d+)\s+(minute|hour|day)s?\s+ago", t)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "minute":
        return datetime.now(timezone.utc) - timedelta(minutes=n)
    if unit == "hour":
        return datetime.now(timezone.utc) - timedelta(hours=n)
    return datetime.now(timezone.utc) - timedelta(days=n)


def scrape_builtinnyc():
    """Scrape Built In NYC product/program manager roles posted in the last 24h.

    Source-specific recency override (24h, not VALID_POST_DAYS). Other filters
    (role, NYC VP-level, salary ≥ MIN_SALARY) reuse shared helpers. Tech-focus
    check is satisfied with the listing tile's text + Top Skills tags so Phase 3
    can skip the Playwright detail fetch for this source.
    """
    log("  [BuiltInNYC] HTTP scrape (24h window)...")
    candidates = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=BUILTIN_RECENCY_HOURS)
    seen_card_ids = set()

    for page_num in range(1, BUILTIN_MAX_PAGES + 1):
        params = dict(BUILTIN_PARAMS)
        params["page"] = str(page_num)
        try:
            resp = requests.get(
                BUILTIN_NYC_BASE,
                params=params,
                headers={"User-Agent": HEADERS["User-Agent"]},
                timeout=20,
            )
        except Exception as e:
            log(f"    [BuiltInNYC] page {page_num} request error: {e}")
            break
        if resp.status_code != 200:
            log(f"    [BuiltInNYC] page {page_num} HTTP {resp.status_code}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("div", attrs={"data-id": "job-card"})
        if not cards:
            break

        new_on_page = 0
        for card in cards:
            card_id = card.get("id", "")
            if card_id and card_id in seen_card_ids:
                continue
            seen_card_ids.add(card_id)
            new_on_page += 1

            title_el = card.find("a", attrs={"data-id": "job-card-title"})
            if not title_el:
                continue
            title = title_el.get_text(" ", strip=True)
            href = title_el.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else f"https://www.builtinnyc.com{href}"

            company_el = card.find("a", attrs={"data-id": "company-title"})
            company = company_el.get_text(strip=True) if company_el else "Unknown"

            card_text = card.get_text(" | ", strip=True)

            posted_dt = parse_builtin_posted(card_text)
            if not posted_dt or posted_dt < cutoff:
                continue

            if not is_target_role(title):
                continue
            if not level_ok(title, "nyc"):
                continue
            if not is_nyc(card_text):
                continue

            sal_match = re.search(
                r"(\$?\d[\d,.]*\s*[KkMm]?\s*[-–]\s*\$?\d[\d,.]*\s*[KkMm]?\s*Annually)",
                card_text,
            )
            salary = sal_match.group(1).strip() if sal_match else ""
            if salary:
                # parse_salary requires a $ prefix; Built In renders "83K-160K Annually".
                normalized = re.sub(
                    r"(?<![\$\d])(\d[\d,.]*\s*[KkMm]?)",
                    r"$\1",
                    salary,
                )
                lo, hi = parse_salary_bounds(normalized)
                if hi is None:
                    continue
                if hi < MIN_SALARY:
                    continue

            posted_label = posted_dt.strftime("%Y-%m-%d")

            job = make_job(
                title=title, url=url, company=company, city="nyc",
                salary=salary, posted=posted_label,
                location="New York, NY, USA", source="builtinnyc",
            )
            # Stash listing text so Phase 3 tech filter can pass without a detail fetch.
            job["description"] = card_text
            candidates.append(job)

        if new_on_page == 0:
            break
        time.sleep(1)

    log(f"  [BuiltInNYC] {len(candidates)} candidate(s)")
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    log("=" * 60)
    log("Jordan's Job Finder — expanded multi-company scan")

    seen     = load_seen()
    new_jobs = []
    shared_jobs = []

    # Cities users picked beyond the built-in metros — multi-list postings in
    # these markets are kept (tagged city="extra") instead of dropped.
    global ACTIVE_EXTRA_CITIES
    ACTIVE_EXTRA_CITIES = load_active_extra_cities()
    if ACTIVE_EXTRA_CITIES:
        log(f"Active extra cities: {', '.join(ACTIVE_EXTRA_CITIES)}")

    # ── Phase 1: No-browser scrapers ──────────────────────────────────────────
    all_candidates = []

    all_candidates += scrape_citi()

    # Fortune 1000 Houston employers on Oracle Cloud / iCIMS.
    all_candidates += collect_houston_extra()

    for name, tenant, ver, site, city in WORKDAY_COMPANIES:
        log(f"  [{name}] Workday...")
        result = scrape_workday_company(name, tenant, ver, site, city)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    for name, token, city in GREENHOUSE_COMPANIES:
        log(f"  [{name}] Greenhouse...")
        result = scrape_greenhouse_company(name, token, city)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    for name, token, city in LEVER_COMPANIES:
        log(f"  [{name}] Lever...")
        result = scrape_lever_company(name, token, city)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    for name, domain, base_url, city in EIGHTFOLD_COMPANIES:
        log(f"  [{name}] Eightfold...")
        result = scrape_eightfold_company(name, domain, base_url, city)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    # ── $1B+ multi-metro employers (one fetch each, metro inferred per posting) ──
    for name, token in GREENHOUSE_MULTI:
        log(f"  [{name}] Greenhouse (multi)...")
        result = scrape_greenhouse_multi(name, token)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    for name, token in LEVER_MULTI:
        log(f"  [{name}] Lever (multi)...")
        result = scrape_lever_multi(name, token)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    for name, tenant, ver, site in WORKDAY_MULTI:
        log(f"  [{name}] Workday (multi)...")
        result = scrape_workday_multi(name, tenant, ver, site)
        log(f"  [{name}] {len(result)} candidate(s)")
        all_candidates += result

    all_candidates += scrape_amazon("nyc")
    all_candidates += scrape_amazon("atlanta")
    all_candidates += scrape_amazon("miami")
    all_candidates += scrape_amazon("dallas")
    all_candidates += scrape_amazon("houston")
    all_candidates += scrape_amazon("dc")

    all_candidates += scrape_builtinnyc()

    # ── Phase 2: Playwright scrapers ──────────────────────────────────────────
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pw_page = browser.new_page(user_agent=HEADERS["User-Agent"])

        all_candidates += scrape_jpmorgan(pw_page)
        all_candidates += scrape_goldman(pw_page)
        all_candidates += scrape_metlife(pw_page)
        all_candidates += scrape_meta(pw_page, "nyc")
        all_candidates += scrape_meta(pw_page, "atlanta")
        all_candidates += scrape_meta(pw_page, "miami")
        all_candidates += scrape_meta(pw_page, "dallas")
        all_candidates += scrape_meta(pw_page, "houston")
        all_candidates += scrape_meta(pw_page, "dc")

        # ── Phase 3: Enrich candidates with detail page ───────────────────────
        log(f"Enriching {len(all_candidates)} candidates with detail pages...")

        for job in all_candidates:
            url = job["url"]
            if not url or url in seen:
                if url in seen:
                    log(f"  Skip duplicate: {job['title'][:55]}")
                continue

            log(f"  Detail: {job['company']} [{job['city'].upper()}] | {job['title'][:50]}")

            is_workday = "myworkdayjobs.com" in url
            is_builtin = job.get("source") == "builtinnyc"

            if is_builtin:
                # Listing tile already has salary/posted/description — skip detail fetch.
                description = job.get("description", "")
                if job["salary"] and not salary_ok(job["salary"]):
                    log(f"    ✗ Salary too low: {job['salary']}")
                    continue
                if not job["salary"]:
                    job["salary"] = "See posting"
                title_lower = job["title"].lower()
                tech_hits = sum(1 for kw in TECH_SIGNALS
                                if kw in description.lower() or kw in title_lower)
                if tech_hits < 2:
                    log(f"    ✗ Not tech-focused (builtin tile, {tech_hits} signals)")
                    continue
            elif is_workday:
                salary, description, posted = fetch_workday_detail(url)
                job["description"] = description
                if salary:
                    job["salary"] = salary
                if posted and posted != "Unknown":
                    job["posted"] = posted
                if not job["salary"]:
                    job["salary"] = "See posting"
            else:
                salary, description, posted = fetch_detail(pw_page, url)
                job["description"] = description
                if salary:
                    job["salary"] = salary
                if posted and posted != "Unknown":
                    job["posted"] = posted

                if job["salary"] and not salary_ok(job["salary"]):
                    if job.get("city") not in SALARY_OPTIONAL_CITIES:
                        log(f"    ✗ Salary too low: {job['salary']}")
                        continue
                    else:
                        log(f"    ⚠ Low salary ({job['salary']}) but city {job['city']} is salary-optional — keeping")
                if not job["salary"]:
                    job["salary"] = "See posting"

                if len(description) > 500:
                    if not is_tech(description):
                        log(f"    ✗ Not tech-focused")
                        continue
                else:
                    # Description didn't load — use title with lower threshold (2 signals)
                    title_lower = job["title"].lower()
                    tech_hits = sum(1 for kw in TECH_SIGNALS if kw in title_lower)
                    if tech_hits < 2:
                        log(f"    ✗ Not tech-focused (title only, {tech_hits} signals)")
                        continue
                time.sleep(1)

            log(f"    ✓ MATCH — {job['salary']} | {job['posted']}")
            new_jobs.append(job)
            shared_jobs.append(normalize_shared_job(job, description))
            seen.add(url)

        browser.close()

    # Persistent store: merge new jobs, purge old ones
    store = load_store()
    store = purge_old_store(store)
    store_urls = {j["url"] for j in store}
    now_iso = datetime.now(timezone.utc).isoformat()
    added = 0
    for job in new_jobs:
        if job["url"] and job["url"] not in store_urls:
            job["found_at"] = now_iso
            store.append(job)
            added += 1
    save_store(store)
    save_shared_jobs(shared_jobs)
    write_html(store)
    save_seen(seen)
    log(f"Done. {added} new job(s) added; {len(store)} total in store")


# ── HTML Output ───────────────────────────────────────────────────────────────

def write_html(jobs):
    run_date = datetime.now().strftime("%B %d, %Y — %I:%M %p")
    illustration_assets = [
        {
            "svg": "https://cdn.undraw.co/illustrations/tasks_l9ct.svg",
            "page": "https://undraw.co/illustration/tasks_l9ct",
            "title": "Tasks",
        },
        {
            "svg": "https://cdn.undraw.co/illustrations/business-analytics_y8m6.svg",
            "page": "https://undraw.co/illustration/business-analytics_y8m6",
            "title": "Business Analytics",
        },
        {
            "svg": "https://cdn.undraw.co/illustrations/analytics_6mru.svg",
            "page": "https://undraw.co/illustration/analytics_6mru",
            "title": "Analytics",
        },
        {
            "svg": "https://cdn.undraw.co/illustrations/in-the-office_ma2b.svg",
            "page": "https://undraw.co/illustration/in-the-office_ma2b",
            "title": "In The Office",
        },
        {
            "svg": "https://cdn.undraw.co/illustrations/working-remotely_ivtz.svg",
            "page": "https://undraw.co/illustration/working-remotely_ivtz",
            "title": "Working Remotely",
        },
        {
            "svg": "https://cdn.undraw.co/illustrations/co-working_becw.svg",
            "page": "https://undraw.co/illustration/co-working_becw",
            "title": "Co Working",
        },
        {
            "svg": "https://cdn.undraw.co/illustrations/business-chat_xea1.svg",
            "page": "https://undraw.co/illustration/business-chat_xea1",
            "title": "Business Chat",
        },
        {
            "svg": "https://cdn.undraw.co/illustrations/contemplating_v4x1.svg",
            "page": "https://undraw.co/illustration/contemplating_v4x1",
            "title": "Contemplating",
        },
    ]

    nyc_jobs = [j for j in jobs if j["city"] == "nyc"]
    atl_jobs = [j for j in jobs if j["city"] == "atlanta"]
    mia_jobs = [j for j in jobs if j["city"] == "miami"]
    city_meta = {
        "nyc": {
            "label": "New York City",
            "kicker": "VP only",
            "accent": "var(--accent-nyc)",
            "description": "Product and program leadership with a premium compensation floor.",
            "empty": "No New York matches landed in the last two days.",
        },
        "atl": {
            "label": "Atlanta",
            "kicker": "VP or Senior",
            "accent": "var(--accent-atl)",
            "description": "Senior and executive PM and PgM roles across enterprise, fintech, and infrastructure.",
            "empty": "No Atlanta matches landed in the last two days.",
        },
        "mia": {
            "label": "Miami",
            "kicker": "VP or Senior",
            "accent": "var(--accent-mia)",
            "description": "South Florida PM and PgM coverage with the same screening logic as Atlanta.",
            "empty": "No Miami matches landed in the last two days.",
        },
    }

    def make_cards(job_list, city):
        if not job_list:
            meta = city_meta[city]
            return f"""
        <div class="empty-state {city}">
          <div class="empty-copy">
            <p class="empty-title">{meta['label']}</p>
            <p class="empty-text">{meta['empty']}</p>
          </div>
        </div>"""
        cards = ""
        for job in job_list:
            cards += f"""
        <article class="card {city}">
          <div class="card-topline">
            <span class="company">{job['company']}</span>
            <span class="posted">{format_posted_label(job)}</span>
          </div>
          <h3 class="title">{job['title']}</h3>
          <div class="meta">
            <span class="meta-chip salary">{job['salary'] or 'Salary not listed'}</span>
            <span class="meta-chip location">{job['location'] or CITY_LABELS.get(job['city'], '')}</span>
          </div>
          <a class="apply-btn" href="{job['url']}" target="_blank" rel="noreferrer">View Role</a>
        </article>"""
        return cards

    nyc_cards = make_cards(nyc_jobs, "nyc")
    atl_cards = make_cards(atl_jobs, "atl")
    mia_cards = make_cards(mia_jobs, "mia")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jordan's Job Finder — {run_date}</title>
<style>
  :root {{
    --bg: #f5f1e8;
    --paper: rgba(255, 255, 255, 0.74);
    --paper-strong: rgba(255, 255, 255, 0.9);
    --ink: #1d2433;
    --muted: #667085;
    --line: rgba(29, 36, 51, 0.1);
    --shadow: 0 28px 60px rgba(29, 36, 51, 0.12);
    --accent-nyc: #1947e5;
    --accent-atl: #b85c38;
    --accent-mia: #1f8f6b;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Avenir Next", "Segoe UI", sans-serif;
    color: var(--ink);
    background:
      radial-gradient(circle at top left, rgba(25, 71, 229, 0.08), transparent 26%),
      radial-gradient(circle at top right, rgba(184, 92, 56, 0.08), transparent 24%),
      linear-gradient(180deg, #f8f4ec 0%, #efe7d8 100%);
    padding: 28px 18px 56px;
  }}
  .page {{
    max-width: 1120px;
    margin: 0 auto;
  }}
  .hero {{
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(260px, 0.8fr);
    gap: 32px;
    align-items: center;
    background: var(--paper);
    border: 1px solid rgba(255, 255, 255, 0.65);
    backdrop-filter: blur(18px);
    border-radius: 28px;
    box-shadow: var(--shadow);
    padding: 34px;
    margin-bottom: 26px;
  }}
  .eyebrow {{
    display: inline-flex;
    align-items: center;
    gap: 10px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.68);
    border: 1px solid rgba(29, 36, 51, 0.08);
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.14em;
    padding: 8px 12px;
    text-transform: uppercase;
    margin-bottom: 18px;
  }}
  h1 {{
    font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
    font-size: clamp(2.3rem, 4vw, 4.25rem);
    line-height: 0.98;
    letter-spacing: -0.04em;
    margin-bottom: 14px;
  }}
  .hero-copy {{
    max-width: 640px;
  }}
  .hero-lead {{
    color: #404b5f;
    font-size: 1rem;
    line-height: 1.7;
    margin-bottom: 22px;
    max-width: 58ch;
  }}
  .hero-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }}
  .hero-pill {{
    border-radius: 999px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.72);
    color: var(--ink);
    font-size: 13px;
    padding: 10px 14px;
  }}
  .hero-visual {{
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(246, 240, 228, 0.88));
    border: 1px solid rgba(29, 36, 51, 0.08);
    border-radius: 24px;
    padding: 18px;
    text-align: center;
  }}
  .hero-visual img {{
    width: 100%;
    max-width: 360px;
    height: auto;
    display: block;
    margin: 0 auto;
  }}
  .credit {{
    color: var(--muted);
    font-size: 12px;
    margin-top: 10px;
  }}
  .credit a {{
    color: inherit;
  }}
  .stats {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 14px;
    margin-bottom: 28px;
  }}
  .stat {{
    background: var(--paper-strong);
    border: 1px solid rgba(255, 255, 255, 0.65);
    border-radius: 20px;
    box-shadow: 0 16px 38px rgba(29, 36, 51, 0.08);
    padding: 20px;
  }}
  .stat-label {{
    display: block;
    color: var(--muted);
    font-size: 12px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 10px;
  }}
  .stat-value {{
    font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
    font-size: 2rem;
    line-height: 1;
  }}
  .sections {{
    display: grid;
    gap: 22px;
  }}
  .section {{
    background: var(--paper);
    border: 1px solid rgba(255, 255, 255, 0.65);
    border-radius: 28px;
    box-shadow: var(--shadow);
    padding: 26px;
  }}
  .section-head {{
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: end;
    border-bottom: 1px solid var(--line);
    padding-bottom: 16px;
    margin-bottom: 18px;
  }}
  .section-kicker {{
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-bottom: 10px;
  }}
  h2 {{
    font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
    font-size: clamp(1.65rem, 2.2vw, 2.2rem);
    line-height: 1.05;
    margin-bottom: 8px;
  }}
  .section-copy {{
    color: #4e596c;
    font-size: 14px;
    line-height: 1.65;
    max-width: 60ch;
  }}
  .section-count {{
    min-width: 86px;
    text-align: right;
    color: var(--muted);
    font-size: 13px;
  }}
  .section-count strong {{
    display: block;
    color: var(--ink);
    font-size: 28px;
    line-height: 1;
  }}
  .card-list {{
    display: grid;
    gap: 14px;
  }}
  .card {{
    background: rgba(255, 255, 255, 0.72);
    border: 1px solid rgba(29, 36, 51, 0.08);
    border-left: 4px solid var(--accent-nyc);
    border-radius: 22px;
    padding: 22px;
  }}
  .card.atl {{ border-left-color: var(--accent-atl); }}
  .card.mia {{ border-left-color: var(--accent-mia); }}
  .card-topline {{
    display: flex;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
  }}
  .company {{
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }}
  .posted  {{
    color: #685c4a;
    font-size: 12px;
    white-space: nowrap;
  }}
  .title {{
    font-size: 1.12rem;
    line-height: 1.45;
    margin-bottom: 14px;
  }}
  .meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 18px;
  }}
  .meta-chip {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border-radius: 999px;
    border: 1px solid rgba(29, 36, 51, 0.08);
    background: rgba(255, 255, 255, 0.82);
    color: #495265;
    font-size: 13px;
    padding: 9px 12px;
  }}
  .salary {{
    color: #1f6f50;
    font-weight: 700;
  }}
  .apply-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 118px;
    border-radius: 999px;
    text-decoration: none;
    background: var(--accent-nyc);
    color: #ffffff;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.02em;
    padding: 11px 16px;
  }}
  .card.atl .apply-btn {{ background: var(--accent-atl); }}
  .card.mia .apply-btn {{ background: var(--accent-mia); }}
  .empty-state {{
    border-radius: 22px;
    border: 1px dashed rgba(29, 36, 51, 0.16);
    background: rgba(255, 255, 255, 0.58);
    padding: 22px;
  }}
  .empty-title {{
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 8px;
  }}
  .empty-text {{
    color: #4e596c;
    font-size: 15px;
    line-height: 1.6;
  }}
  @media (max-width: 920px) {{
    .hero {{
      grid-template-columns: 1fr;
      padding: 24px;
    }}
    .stats {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .section-head {{
      flex-direction: column;
      align-items: start;
    }}
    .section-count {{
      text-align: left;
    }}
  }}
  @media (max-width: 640px) {{
    body {{
      padding: 18px 14px 36px;
    }}
    .stats {{
      grid-template-columns: 1fr;
    }}
    .hero,
    .section {{
      border-radius: 22px;
      padding: 20px;
    }}
    .card {{
      padding: 18px;
    }}
    .card-topline {{
      flex-direction: column;
      align-items: start;
    }}
    .posted {{
      white-space: normal;
    }}
  }}
</style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-copy">
        <span class="eyebrow">Curated Leadership Search</span>
        <h1>Jordan's Job Finder</h1>
        <p class="hero-lead">
          A focused board for product and program management roles across New York City, Atlanta, and Miami. The scraper reviews selected company career pages and surfaces only the matches that clear the current role, location, recency, and compensation filters.
        </p>
        <div class="hero-meta">
          <span class="hero-pill">Last run: {run_date}</span>
          <span class="hero-pill">Live public website</span>
          <span class="hero-pill">PM / PgM only</span>
        </div>
      </div>
      <div class="hero-visual">
        <img
          id="hero-illustration"
          src="{illustration_assets[0]['svg']}"
          alt="{illustration_assets[0]['title']} illustration by unDraw"
          data-illustrations='{json.dumps(illustration_assets)}'
        >
        <p class="credit">Illustration by <a id="hero-illustration-link" href="{illustration_assets[0]['page']}" target="_blank" rel="noreferrer">unDraw</a></p>
      </div>
    </section>

    <section class="stats">
      <div class="stat">
        <span class="stat-label">New York City</span>
        <strong class="stat-value">{len(nyc_jobs)}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">Atlanta</span>
        <strong class="stat-value">{len(atl_jobs)}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">Miami</span>
        <strong class="stat-value">{len(mia_jobs)}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">Total Live Matches</span>
        <strong class="stat-value">{len(jobs)}</strong>
      </div>
    </section>

    <section class="sections">
      <section class="section">
        <div class="section-head">
          <div>
            <p class="section-kicker">NYC · {city_meta['nyc']['kicker']}</p>
            <h2>New York City</h2>
            <p class="section-copy">{city_meta['nyc']['description']}</p>
          </div>
          <div class="section-count"><strong>{len(nyc_jobs)}</strong>matches</div>
        </div>
        <div class="card-list">
          {nyc_cards}
        </div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <p class="section-kicker">Atlanta · {city_meta['atl']['kicker']}</p>
            <h2>Atlanta</h2>
            <p class="section-copy">{city_meta['atl']['description']}</p>
          </div>
          <div class="section-count"><strong>{len(atl_jobs)}</strong>matches</div>
        </div>
        <div class="card-list">
          {atl_cards}
        </div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <p class="section-kicker">Miami · {city_meta['mia']['kicker']}</p>
            <h2>Miami</h2>
            <p class="section-copy">{city_meta['mia']['description']}</p>
          </div>
          <div class="section-count"><strong>{len(mia_jobs)}</strong>matches</div>
        </div>
        <div class="card-list">
          {mia_cards}
        </div>
      </section>
    </section>
  </div>
  <script>
    (() => {{
      const image = document.getElementById("hero-illustration");
      const link = document.getElementById("hero-illustration-link");
      if (!image || !link) return;

      const raw = image.dataset.illustrations;
      if (!raw) return;

      let illustrations = [];
      try {{
        illustrations = JSON.parse(raw);
      }} catch (_error) {{
        return;
      }}
      if (!illustrations.length) return;

      const formatter = new Intl.DateTimeFormat("en-CA", {{
        timeZone: "America/New_York",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }});
      const hourFormatter = new Intl.DateTimeFormat("en-US", {{
        timeZone: "America/New_York",
        hour: "2-digit",
        hour12: false,
      }});

      const now = new Date();
      const nyDateKey = formatter.format(now);
      const nyHour = Number(hourFormatter.format(now));
      const [year, month, day] = nyDateKey.split("-").map(Number);
      const anchorDay = nyHour < 6 ? day - 1 : day;
      const rotationSeed = Date.UTC(year, month - 1, anchorDay);
      const index = Math.abs(Math.floor(rotationSeed / 86400000)) % illustrations.length;
      const asset = illustrations[index];

      image.src = asset.svg;
      image.alt = `${{asset.title}} illustration by unDraw`;
      link.href = asset.page;
    }})();
  </script>
</body>
</html>"""

    OUTPUT_FILE.write_text(html)


if __name__ == "__main__":
    main()
