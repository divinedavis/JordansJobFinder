"""Single source of truth for the metros this app covers.

Before 2026-07-21 every scraper carried its own copy of the metro patterns —
six near-identical dicts that drifted apart and had to be fixed six times when
a collision showed up. This module replaces all of them.

## The set

**The 20 largest US metros** (2025 Census MSA estimates), plus two groups kept
deliberately:

* **Central/eastern PA** — York, Lancaster, Harrisburg. These are reachable
  only through the regional ATS platforms in scraper_ats_extra.py, and they're
  the whole IT-track audience.
* **South Carolina's 10 largest cities.** Eight already fall inside the four SC
  metros (Charleston covers North Charleston / Mount Pleasant / Summerville /
  Goose Creek; Greenville covers Greer), so only Sumter and Florence are new.

San Antonio, Jacksonville, Orlando and the florida-other catch-all were dropped
on 2026-07-21 — outside the top 20 and outside both keep-lists.

## Pattern rules

Matching is substring-against-lowercased-location, so:

1. **State-qualify anything ambiguous.** "denver, co" not "denver" — Denver PA
   sits in Lancaster County. Bare names are reserved for genuinely unique
   places (Minneapolis, Seattle, Philadelphia).
2. **Order matters** — `MATCH_ORDER` is checked first-match-wins, so
   catch-alls go last. Dallas carries ", tx"/"texas" and must stay at the end.
3. **Collisions get a decoy, not a reorder** — see metro_decoys.py. Reordering
   only helps the metro you move; the true metro can't be first for everyone.

Boundaries follow the local labor market rather than strict MSA lines, matching
what this codebase already did (Greenville has always included Spartanburg, a
separate MSA). So the Bay Area includes San Jose and Detroit includes Ann
Arbor — the goal is finding jobs people would actually commute to.
"""

# ── The 20 largest US metros, in population order ─────────────────────────────

TOP_20 = (
    "nyc", "la", "chicago", "dallas", "houston", "atlanta", "dc", "miami",
    "philadelphia-pa", "phoenix", "boston", "riverside", "san-francisco",
    "detroit", "seattle", "minneapolis", "tampa-fl", "san-diego", "denver",
    "baltimore-md",
)

# Kept outside the top 20: the PA trio (IT-track audience, and the only metros
# the regional ATS platforms reach) and South Carolina.
PA_REGIONAL = ("york-pa", "lancaster-pa", "harrisburg-pa")
SC_REGIONAL = ("charleston-sc", "columbia-sc", "greenville-sc", "rock-hill-sc",
               "sumter-sc", "florence-sc")

LABELS = {
    "nyc": "New York, NY",
    "la": "Los Angeles, CA",
    "chicago": "Chicago, IL",
    "dallas": "Dallas, TX",
    "houston": "Houston, TX",
    "atlanta": "Atlanta, GA",
    "dc": "Washington, DC",
    "miami": "Miami, FL",
    "philadelphia-pa": "Philadelphia, PA",
    "phoenix": "Phoenix, AZ",
    "boston": "Boston, MA",
    "riverside": "Riverside, CA",
    "san-francisco": "San Francisco, CA",
    "detroit": "Detroit, MI",
    "seattle": "Seattle, WA",
    "minneapolis": "Minneapolis, MN",
    "tampa-fl": "Tampa, FL",
    "san-diego": "San Diego, CA",
    "denver": "Denver, CO",
    "baltimore-md": "Baltimore, MD",
    "york-pa": "York, PA",
    "lancaster-pa": "Lancaster, PA",
    "harrisburg-pa": "Harrisburg, PA",
    "charleston-sc": "Charleston, SC",
    "columbia-sc": "Columbia, SC",
    "greenville-sc": "Greenville, SC",
    "rock-hill-sc": "Rock Hill, SC",
    "sumter-sc": "Sumter, SC",
    "florence-sc": "Florence, SC",
}

PATTERNS = {
    "nyc": ("new york", "nyc", "manhattan", "brooklyn", "queens, ny",
            "bronx", "staten island", "jersey city", "hoboken", "newark, nj",
            "long island city", "white plains", "stamford, ct", "yonkers"),
    "la": ("los angeles", "l.a.", "greater los angeles", "socal",
           "santa monica", "culver city", "long beach", "pasadena, ca",
           "burbank", "glendale, ca", "el segundo", "marina del rey",
           "playa vista", "venice, ca", "west hollywood", "hawthorne",
           "gardena", "sherman oaks", "westwood", "century city",
           "torrance", "manhattan beach", "redondo beach", "inglewood",
           "van nuys", "studio city", "north hollywood", "woodland hills",
           "santa clarita", "calabasas", "beverly hills", "ventura",
           "newport beach", "irvine", "anaheim", "santa ana", "costa mesa",
           "lancaster, ca", "palmdale",
           "huntington beach", "orange, ca", "fullerton", "cerritos"),
    "chicago": ("chicago", "evanston", "naperville", "schaumburg",
                "rosemont, il", "oak brook", "oakbrook", "deerfield, il",
                "vernon hills", "lincolnshire", "northbrook",
                "downers grove", "des plaines", "skokie", "itasca",
                "hoffman estates", "lake forest, il", "aurora, il",
                "riverside, il", "brookfield, il", "la grange, il",
                "elgin, il", "joliet", "arlington heights", "bolingbrook",
                "oak lawn", "berwyn, il", "wheaton", "elmhurst"),
    "dallas": ("dallas", "fort worth", "dfw", "plano", "irving",
               "arlington, tx", "frisco", "richardson", "addison",
               "mckinney", "allen, tx", "carrollton", "grapevine",
               "lewisville", "denton, tx", "garland", "mesquite, tx"),
    "houston": ("houston", "the woodlands", "sugar land", "katy",
                "spring, tx", "pasadena, tx", "cypress, tx", "pearland",
                "humble", "baytown", "conroe", "league city", "missouri city",
                "stafford, tx", "richmond, tx", "friendswood"),
    "atlanta": ("atlanta", "alpharetta", "buckhead", "sandy springs",
                "dunwoody", "marietta", "roswell, ga", "duluth, ga",
                "kennesaw", "smyrna, ga", "norcross", "peachtree",
                "johns creek", "decatur, ga"),
    "dc": ("washington, dc", "washington dc", "washington, d.c.", "d.c.",
           "arlington, va", "mclean", "tysons", "reston", "bethesda",
           "rockville", "silver spring", "fairfax", "herndon", "chantilly",
           "vienna, va", "springfield, va", "gaithersburg", "college park",
           "alexandria, va", "northern virginia", "nova", "dulles"),
    "miami": ("miami", "miami beach", "miami-dade", "greater miami",
              "south florida", "brickell", "coral gables", "doral",
              "fort lauderdale", "ft lauderdale", "aventura", "boca raton",
              "hialeah", "hollywood, fl", "pembroke pines", "sunrise, fl",
              "plantation, fl", "weston, fl", "west palm beach",
              "delray beach", "pompano beach", "oakland park"),
    "philadelphia-pa": ("philadelphia", "philly", "conshohocken",
                        "king of prussia", "wayne, pa", "radnor", "malvern",
                        "horsham", "camden, nj", "wilmington, de", "yardley",
                        "chesterbrook", "plymouth meeting", "newtown square",
                        "berwyn, pa", "west chester, pa", "blue bell",
                        "fort washington, pa", "rosemont, pa", "valley forge",
                        "bala cynwyd", "media, pa", "exton", "chadds ford"),
    "phoenix": ("phoenix", "scottsdale", "tempe", "chandler",
                "mesa, az", "gilbert, az", "glendale, az", "peoria, az",
                "goodyear, az", "surprise, az", "avondale, az", "tolleson",
                "queen creek", "fountain hills"),
    "boston": ("boston", "cambridge, ma", "somerville, ma", "waltham",
               "burlington, ma", "quincy, ma", "newton, ma", "brookline",
               "lexington, ma", "needham", "woburn", "bedford, ma",
               "andover", "lowell", "framingham", "marlborough", "natick",
               "dedham", "braintree", "canton, ma", "norwood, ma",
               "wakefield, ma", "peabody", "salem, ma", "medford, ma",
               "malden", "chelsea, ma", "everett, ma", "watertown, ma",
               "billerica", "chelmsford", "wilmington, ma", "weymouth",
               "hingham", "seaport district", "greater boston"),
    "riverside": ("riverside, ca", "san bernardino", "ontario, ca",
                  "rancho cucamonga", "moreno valley", "corona, ca",
                  "temecula", "murrieta", "fontana", "victorville",
                  "hesperia", "redlands", "chino", "palm springs", "indio",
                  "hemet", "menifee", "eastvale", "jurupa valley", "yucaipa",
                  "beaumont, ca", "perris", "lake elsinore", "coachella",
                  "colton", "rialto", "upland, ca", "inland empire"),
    "san-francisco": ("san francisco", "sf bay", "bay area", "oakland, ca",
                      "berkeley", "palo alto", "mountain view", "sunnyvale",
                      "santa clara", "san jose", "cupertino", "menlo park",
                      "redwood city", "fremont, ca", "san mateo",
                      "foster city", "emeryville", "alameda, ca",
                      "walnut creek", "pleasanton", "san ramon", "milpitas",
                      "burlingame", "daly city", "richmond, ca",
                      "concord, ca", "hayward", "south san francisco",
                      "novato", "san rafael", "silicon valley", "campbell, ca",
                      "los gatos", "saratoga, ca", "dublin, ca"),
    "detroit": ("detroit", "ann arbor", "dearborn", "troy, mi", "warren, mi",
                "southfield", "farmington hills", "livonia", "novi",
                "sterling heights", "auburn hills", "rochester hills",
                "royal oak", "pontiac", "plymouth, mi", "canton, mi",
                "westland", "taylor, mi", "dearborn heights",
                "st. clair shores", "roseville, mi", "madison heights",
                "birmingham, mi", "bloomfield hills", "wixom", "allen park"),
    "seattle": ("seattle", "bellevue", "redmond, wa", "kirkland, wa",
                "tacoma", "everett, wa", "renton", "bothell", "issaquah",
                "sammamish", "kent, wa", "federal way", "lynnwood",
                "shoreline, wa", "auburn, wa", "puyallup", "olympia",
                "bremerton", "mercer island", "tukwila", "seatac",
                "woodinville", "puget sound"),
    "minneapolis": ("minneapolis", "st. paul", "saint paul", "st paul",
                    "bloomington, mn", "eagan", "eden prairie",
                    "plymouth, mn", "maple grove", "woodbury, mn",
                    "burnsville", "edina", "minnetonka", "st. louis park",
                    "richfield, mn", "roseville, mn", "brooklyn park",
                    "brooklyn center", "coon rapids", "blaine, mn",
                    "lakeville, mn", "apple valley, mn", "chanhassen",
                    "chaska", "shakopee", "golden valley", "arden hills",
                    "mendota heights", "inver grove", "hopkins, mn",
                    "wayzata", "twin cities"),
    "tampa-fl": ("tampa", "st. petersburg, fl", "saint petersburg, fl",
                 "clearwater", "brandon, fl", "lakeland", "largo, fl",
                 "palm harbor", "wesley chapel", "riverview, fl",
                 "plant city", "oldsmar", "temple terrace", "tampa bay"),
    "san-diego": ("san diego", "la jolla", "carlsbad", "sorrento valley",
                  "chula vista", "oceanside", "escondido", "encinitas",
                  "del mar", "poway", "national city", "rancho bernardo",
                  "mira mesa", "torrey pines", "vista, ca", "san marcos, ca"),
    "denver": ("denver, co", "denver co", "aurora, co", "lakewood, co",
               "boulder, co", "westminster, co", "arvada", "thornton, co",
               "centennial, co", "highlands ranch", "littleton",
               "englewood, co", "broomfield", "greenwood village",
               "louisville, co", "lone tree", "castle rock", "parker, co",
               "commerce city", "wheat ridge", "golden, co", "superior, co",
               "northglenn", "brighton, co", "denver metro", "front range"),
    "baltimore-md": ("baltimore", "owings mills", "columbia, md", "towson",
                     "hunt valley", "sparks, md", "linthicum", "annapolis",
                     "bel air", "catonsville", "glen burnie", "white marsh",
                     "cockeysville", "elkridge", "hanover, md",
                     "aberdeen, md", "lutherville", "timonium"),

    # ── Central / eastern PA ──────────────────────────────────────────────
    "york-pa": ("york, pa", "york county, pa", "red lion, pa",
                "hanover, pa", "dover, pa", "spring grove, pa"),
    "lancaster-pa": ("lancaster, pa", "lancaster county", "lititz",
                     "ephrata", "denver, pa", "columbia, pa", "manheim",
                     "elizabethtown, pa", "millersville"),
    "harrisburg-pa": ("harrisburg", "camp hill", "mechanicsburg",
                      "hershey, pa", "carlisle, pa", "lemoyne",
                      "middletown, pa", "enola", "new cumberland"),

    # ── South Carolina's 10 largest cities ────────────────────────────────
    "charleston-sc": ("charleston, sc", "charleston sc", "north charleston",
                      "mount pleasant", "mt pleasant", "summerville",
                      "ladson", "goose creek", "moncks corner", "hanahan",
                      "daniel island", "ridgeville", "lowcountry"),
    "columbia-sc": ("columbia, sc", "columbia sc", "lexington, sc",
                    "west columbia", "cayce", "irmo", "blythewood",
                    "richland county", "midlands"),
    "greenville-sc": ("greenville, sc", "greenville sc", "spartanburg",
                      "greer", "simpsonville", "mauldin", "anderson, sc",
                      "easley", "duncan, sc", "upstate"),
    "rock-hill-sc": ("rock hill", "fort mill", "york, sc", "york county, sc",
                     "tega cay", "clover, sc"),
    "sumter-sc": ("sumter, sc", "sumter sc", "shaw afb", "shaw air force"),
    "florence-sc": ("florence, sc", "florence sc", "florence county, sc"),
}

# First match wins, so this is ordered most-specific to most-permissive.
#
# * The PA and SC metros lead: they're all state-qualified and several of their
#   place names ("denver, pa", "columbia, pa", "york, sc") would otherwise be
#   claimed by a bigger metro further down.
# * Phoenix precedes LA so "Glendale, AZ" beats LA's "glendale, ca", and
#   Riverside precedes LA so the Inland Empire doesn't get swallowed.
# * Minneapolis precedes NYC so "Brooklyn Park, MN" resolves correctly even
#   without its decoy.
# * Dallas is LAST — its ", tx"/"texas" catch-alls would otherwise swallow
#   Houston. Atlanta and Phoenix carry the same kind of state catch-all and sit
#   as late as their own collisions allow.
MATCH_ORDER = (
    # State-qualified regionals first.
    "york-pa", "lancaster-pa", "harrisburg-pa",
    "charleston-sc", "columbia-sc", "greenville-sc", "rock-hill-sc",
    "sumter-sc", "florence-sc",
    # Then the top 20, specific before catch-all.
    "minneapolis", "seattle", "denver", "boston", "detroit",
    "san-francisco", "riverside", "san-diego", "philadelphia-pa",
    "baltimore-md", "tampa-fl", "nyc", "miami", "chicago",
    "phoenix", "la", "dc", "atlanta", "houston", "dallas",
)

ALL_METROS = MATCH_ORDER

assert set(MATCH_ORDER) == set(PATTERNS) == set(LABELS), (
    "MATCH_ORDER, PATTERNS and LABELS must cover exactly the same metros"
)
assert set(TOP_20) | set(PA_REGIONAL) | set(SC_REGIONAL) == set(MATCH_ORDER)


# Bare state tokens, used ONLY when the caller already knows which metro it is
# scraping (the per-city Workday/Greenhouse lists, where a posting's location
# is sometimes just ", TX"). They are deliberately kept OUT of PATTERNS: in
# multi-metro inference a catch-all silently relabels every job in the state as
# the big metro. Before this split, dropping San Antonio turned every San
# Antonio posting into a Dallas one instead of excluding it, and "Savannah, GA"
# read as Atlanta.
STATE_FALLBACK = {
    "dallas": ("tx,", ", tx", "texas"),
    "houston": ("tx,", ", tx", "texas"),
    "atlanta": ("ga,", ", ga", "georgia"),
    "phoenix": ("az,", ", az", "arizona"),
}


def matches_metro(location, slug, allow_state_fallback=False):
    """Whether `location` sits in `slug`.

    `allow_state_fallback` is for per-city scraping only — see STATE_FALLBACK.
    """
    from metro_decoys import strip_decoys

    text = strip_decoys((location or "").lower(), slug)
    if not text:
        return False
    if any(pattern in text for pattern in PATTERNS.get(slug, ())):
        return True
    if allow_state_fallback:
        return any(p in text for p in STATE_FALLBACK.get(slug, ()))
    return False


def infer_metro(location, allowed=None):
    """First metro whose patterns match `location`, or "" when none do.

    `allowed` restricts the search to a subset of slugs — used by verticals
    that intentionally cover fewer metros than the full set.
    """
    from metro_decoys import strip_decoys

    text = (location or "").lower()
    if not text:
        return ""
    for slug in MATCH_ORDER:
        if allowed is not None and slug not in allowed:
            continue
        # Blank out place names that only *contain* this metro's token, so
        # NYC's bare "manhattan" can't claim "Manhattan Beach, CA".
        candidate = strip_decoys(text, slug)
        if any(pattern in candidate for pattern in PATTERNS[slug]):
            return slug
    return ""


# Metros this app no longer scrapes. Kept for DISPLAY ONLY so job rows and
# saved searches written before 2026-07-21 still render a city name instead of
# a blank while they age off the board. Never add these to MATCH_ORDER.
RETIRED_LABELS = {
    "san-antonio": "San Antonio, TX",
    "jacksonville-fl": "Jacksonville, FL",
    "orlando-fl": "Orlando, FL",
    "florida-other": "Florida (other)",
}

# What the UI should use to turn a stored slug into text.
DISPLAY_LABELS = {**RETIRED_LABELS, **LABELS}


def label_for(slug):
    return DISPLAY_LABELS.get(slug, "")
