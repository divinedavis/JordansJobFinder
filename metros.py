"""Single source of truth for the metros this app covers.

Before 2026-07-21 every scraper carried its own copy of the metro patterns —
six near-identical dicts that drifted apart and had to be fixed six times when
a collision showed up. This module replaces all of them.

## The set

**The 20 largest US metros** (2025 Census MSA estimates), plus three groups kept
deliberately:

* **Central/eastern PA** — York, Lancaster, Harrisburg. These are reachable
  only through the regional ATS platforms in scraper_ats_extra.py, and they're
  the whole IT-track audience.
* **North Carolina, South Carolina and Georgia — every city** (2026-08-26,
  owner's request). One metro per MSA in each state, plus a statewide
  catch-all (`nc-other` / `sc-other` / `ga-other`) checked after every named
  metro, so a posting in a town too small for an MSA still lands on the board
  under "North Carolina (other)" rather than being dropped. Atlanta's pattern
  list was widened at the same time — it had a dozen inner suburbs, and with a
  Georgia catch-all in play everything in Cobb/Gwinnett/Douglas/Paulding would
  have read as "Georgia (other)".
* **International** — Lagos, Nigeria (added 2026-08-01, owner's request). The
  first non-US metro in the registry. Nothing else in the app assumes US-only,
  but note that no employer list targets Nigeria: Lagos fills only when one of
  the existing $1B+ employers posts a Lagos role on its Workday/Greenhouse
  board and it survives the track's title + recency filters. To make it a
  first-class market, add Nigerian employers the way scraper_sc_employers.py
  did for South Carolina.

San Antonio, Jacksonville, Orlando and the florida-other catch-all were dropped
on 2026-07-21 — outside the top 20 and outside both keep-lists.

## Pattern rules

Matching is substring-against-lowercased-location, so:

1. **State-qualify anything ambiguous.** "denver, co" not "denver" — Denver PA
   sits in Lancaster County. Bare names are reserved for genuinely unique
   places (Minneapolis, Seattle, Philadelphia) — and for those, the lookalikes
   go in metro_decoys.py. Lagos NG is the worked example: its real postings are
   written every which way ("Lagos, Nigeria", "NGA05-01-Lagos-Bishop Aboyade
   Cole Street"), while its lookalikes are a short, closed list (Los Lagos in
   Chile, Lagos de Moreno in Mexico, Lagos in Portugal). Enumerate whichever
   side is finite.
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

# ── The Carolinas + Georgia: every city in the three states (2026-08-26) ──────
#
# Owner asked for "all cities in NC, SC and GA". The registry is metro-shaped,
# not city-shaped, so the way to cover a whole state is: one metro per
# metropolitan statistical area (that's where the employers are, and it's what
# makes a useful dashboard section), plus a **statewide catch-all** checked
# LAST — so a posting in a town too small to have an MSA lands on
# "North Carolina (other)" instead of falling off the board. Between the two,
# no city in these three states can be dropped.
#
# The catch-alls are the only bare state tokens in PATTERNS, and they are safe
# here for the reason STATE_FALLBACK is not: the label they produce IS the
# state, so a Hickory job reads "North Carolina (other)", never "Charlotte".
# The card still shows the posting's own location — see results._card_city.
NC_REGIONAL = ("charlotte-nc", "raleigh-nc", "durham-nc", "greensboro-nc",
               "winston-salem-nc", "fayetteville-nc", "asheville-nc",
               "wilmington-nc", "hickory-nc", "greenville-nc",
               "jacksonville-nc", "burlington-nc", "new-bern-nc",
               "rocky-mount-nc", "goldsboro-nc", "nc-other")
SC_REGIONAL = ("charleston-sc", "columbia-sc", "greenville-sc", "rock-hill-sc",
               "myrtle-beach-sc", "hilton-head-sc", "sumter-sc", "florence-sc",
               "sc-other")
GA_REGIONAL = ("augusta-ga", "savannah-ga", "columbus-ga", "macon-ga",
               "athens-ga", "gainesville-ga", "warner-robins-ga", "albany-ga",
               "dalton-ga", "valdosta-ga", "rome-ga", "brunswick-ga",
               "hinesville-ga", "ga-other")
# Every statewide catch-all, so display code can tell "we know the metro" from
# "we only know the state".
STATEWIDE_CATCH_ALLS = frozenset({"nc-other", "sc-other", "ga-other"})
# Non-US markets. Kept as its own group so the US-only assumptions elsewhere
# (STATE_FALLBACK, normalize_states, uscities.py) stay visibly US-scoped.
INTERNATIONAL = ("lagos-ng",)

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
    "myrtle-beach-sc": "Myrtle Beach, SC",
    "hilton-head-sc": "Hilton Head, SC",
    "sumter-sc": "Sumter, SC",
    "florence-sc": "Florence, SC",
    "sc-other": "South Carolina (other)",
    "charlotte-nc": "Charlotte, NC",
    "raleigh-nc": "Raleigh, NC",
    "durham-nc": "Durham, NC",
    "greensboro-nc": "Greensboro, NC",
    "winston-salem-nc": "Winston-Salem, NC",
    "fayetteville-nc": "Fayetteville, NC",
    "asheville-nc": "Asheville, NC",
    "wilmington-nc": "Wilmington, NC",
    "hickory-nc": "Hickory, NC",
    "greenville-nc": "Greenville, NC",
    "jacksonville-nc": "Jacksonville, NC",
    "burlington-nc": "Burlington, NC",
    "new-bern-nc": "New Bern, NC",
    "rocky-mount-nc": "Rocky Mount, NC",
    "goldsboro-nc": "Goldsboro, NC",
    "nc-other": "North Carolina (other)",
    "augusta-ga": "Augusta, GA",
    "savannah-ga": "Savannah, GA",
    "columbus-ga": "Columbus, GA",
    "macon-ga": "Macon, GA",
    "athens-ga": "Athens, GA",
    "gainesville-ga": "Gainesville, GA",
    "warner-robins-ga": "Warner Robins, GA",
    "albany-ga": "Albany, GA",
    "dalton-ga": "Dalton, GA",
    "valdosta-ga": "Valdosta, GA",
    "rome-ga": "Rome, GA",
    "brunswick-ga": "Brunswick, GA",
    "hinesville-ga": "Hinesville, GA",
    "ga-other": "Georgia (other)",
    "lagos-ng": "Lagos, Nigeria",
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
                "johns creek", "decatur, ga", "brookhaven, ga", "chamblee",
                "doraville", "tucker, ga", "stone mountain", "lithonia",
                "stonecrest", "conyers", "covington, ga", "snellville",
                "lilburn", "lawrenceville", "suwanee", "buford",
                "sugar hill, ga", "cumming, ga", "milton, ga", "canton, ga",
                "woodstock, ga", "acworth", "powder springs", "austell",
                "mableton", "lithia springs", "douglasville", "villa rica",
                "dallas, ga", "hiram, ga", "cartersville", "carrollton, ga",
                "newnan", "fayetteville, ga", "mcdonough", "stockbridge",
                "jonesboro, ga", "morrow, ga", "riverdale, ga",
                "forest park, ga", "union city, ga", "east point, ga",
                "college park, ga", "hapeville", "griffin, ga",
                "fulton county, ga", "dekalb county, ga",
                "cobb county, ga", "gwinnett"),
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

    # ── South Carolina, the rest ──────────────────────────────────────────
    "myrtle-beach-sc": ("myrtle beach", "north myrtle beach", "conway, sc",
                        "surfside beach", "murrells inlet", "socastee",
                        "little river, sc", "horry county", "georgetown, sc",
                        "pawleys island", "grand strand"),
    "hilton-head-sc": ("hilton head", "bluffton, sc", "beaufort, sc",
                       "port royal, sc", "okatie", "parris island",
                       "ridgeland, sc", "hardeeville", "lowcountry, sc"),

    # ── North Carolina ────────────────────────────────────────────────────
    "charlotte-nc": ("charlotte", "concord, nc", "gastonia", "huntersville",
                     "matthews, nc", "mint hill", "pineville, nc",
                     "cornelius, nc", "davidson, nc", "mooresville",
                     "kannapolis", "monroe, nc", "indian trail", "waxhaw",
                     "harrisburg, nc", "belmont, nc", "mount holly, nc",
                     "denver, nc", "dallas, nc", "lincolnton", "shelby, nc",
                     "statesville", "salisbury, nc", "ballantyne",
                     "lowell, nc", "cramerton", "mecklenburg", "gaston county"),
    "raleigh-nc": ("raleigh", "cary, nc", "apex, nc", "morrisville",
                   "wake forest", "garner, nc", "holly springs",
                   "fuquay", "knightdale", "wendell, nc", "zebulon",
                   "rolesville", "clayton, nc", "smithfield, nc",
                   "wake county"),
    "durham-nc": ("durham, nc", "durham nc", "chapel hill", "carrboro",
                  "hillsborough, nc", "research triangle", "rtp, nc",
                  "durham county"),
    "greensboro-nc": ("greensboro", "high point, nc", "jamestown, nc",
                      "oak ridge, nc", "summerfield, nc", "guilford county",
                      "archdale", "asheboro"),
    "winston-salem-nc": ("winston-salem", "winston salem", "kernersville",
                         "clemmons", "lewisville, nc", "walkertown",
                         "king, nc", "bermuda run", "mocksville",
                         "forsyth county"),
    "fayetteville-nc": ("fayetteville, nc", "fayetteville nc", "fort bragg",
                        "fort liberty", "hope mills", "spring lake, nc",
                        "raeford", "pope field", "pope army",
                        "cumberland county, nc"),
    "asheville-nc": ("asheville", "hendersonville, nc", "arden, nc",
                     "fletcher, nc", "black mountain, nc", "weaverville",
                     "waynesville", "brevard, nc", "biltmore",
                     "buncombe county"),
    "wilmington-nc": ("wilmington, nc", "wilmington nc", "leland, nc",
                      "carolina beach", "wrightsville beach", "kure beach",
                      "castle hayne", "hampstead", "southport, nc",
                      "new hanover"),
    "hickory-nc": ("hickory, nc", "conover, nc", "newton, nc", "morganton",
                   "lenoir, nc", "valdese", "granite falls, nc",
                   "taylorsville, nc", "catawba county"),
    "greenville-nc": ("greenville, nc", "greenville nc", "winterville, nc",
                      "ayden", "farmville, nc", "bethel, nc",
                      "washington, nc", "pitt county"),
    "jacksonville-nc": ("jacksonville, nc", "jacksonville nc", "camp lejeune",
                        "lejeune", "richlands, nc", "swansboro", "hubert, nc",
                        "onslow county"),
    "burlington-nc": ("burlington, nc", "graham, nc", "mebane", "elon, nc",
                      "gibsonville", "haw river", "alamance county"),
    "new-bern-nc": ("new bern", "newbern", "havelock", "morehead city",
                    "cherry point", "trent woods", "james city, nc",
                    "craven county"),
    "rocky-mount-nc": ("rocky mount", "wilson, nc", "nashville, nc",
                       "tarboro", "battleboro", "nash county",
                       "edgecombe county"),
    "goldsboro-nc": ("goldsboro", "seymour johnson", "kinston",
                     "mount olive, nc", "la grange, nc", "pikeville, nc",
                     "snow hill, nc", "wayne county, nc"),

    # ── Georgia, outside metro Atlanta ────────────────────────────────────
    "augusta-ga": ("augusta, ga", "augusta ga", "martinez, ga", "evans, ga",
                   "grovetown", "north augusta", "aiken, sc", "fort gordon",
                   "fort eisenhower", "thomson, ga", "richmond county, ga",
                   "columbia county, ga"),
    "savannah-ga": ("savannah", "pooler", "garden city, ga",
                    "richmond hill, ga", "port wentworth", "tybee island",
                    "rincon, ga", "bloomingdale, ga", "hunter army",
                    "chatham county, ga"),
    "columbus-ga": ("columbus, ga", "columbus ga", "fort benning",
                    "fort moore", "phenix city", "midland, ga",
                    "muscogee county", "harris county, ga"),
    "macon-ga": ("macon", "bibb county", "byron, ga", "forsyth, ga",
                 "gray, ga", "jones county, ga"),
    "athens-ga": ("athens, ga", "athens ga", "athens-clarke", "watkinsville",
                  "bogart, ga", "winterville, ga", "clarke county, ga",
                  "oconee county, ga"),
    "gainesville-ga": ("gainesville, ga", "gainesville ga", "oakwood, ga",
                       "flowery branch", "braselton", "dahlonega",
                       "hall county, ga"),
    "warner-robins-ga": ("warner robins", "robins air force", "robins afb",
                         "centerville, ga", "perry, ga", "bonaire, ga",
                         "houston county, ga"),
    "albany-ga": ("albany, ga", "albany ga", "leesburg, ga",
                  "dougherty county", "lee county, ga"),
    "dalton-ga": ("dalton, ga", "dalton ga", "chatsworth, ga", "rocky face",
                  "tunnel hill", "calhoun, ga", "whitfield county",
                  "murray county, ga"),
    "valdosta-ga": ("valdosta", "hahira", "remerton", "lake park, ga",
                    "moody air force", "moody afb", "lowndes county, ga"),
    "rome-ga": ("rome, ga", "rome ga", "cave spring, ga", "cedartown",
                "rockmart", "armuchee", "floyd county, ga"),
    "brunswick-ga": ("brunswick, ga", "brunswick ga", "st. simons",
                     "st simons", "saint simons", "jekyll island",
                     "kingsland, ga", "st. marys, ga", "glynn county"),
    "hinesville-ga": ("hinesville", "fort stewart", "flemington, ga",
                      "midway, ga", "walthourville", "liberty county, ga"),

    # ── Statewide catch-alls ──────────────────────────────────────────────
    # Checked LAST, after every named metro in the same state, so these only
    # ever fire for a town nothing else claimed. A bare state token is exactly
    # what STATE_FALLBACK exists to keep OUT of inference — the difference is
    # that these do not lie about which market the job is in: the label is the
    # state, and the card shows the posting's own location.
    "nc-other": ("north carolina", ", nc"),
    "sc-other": ("south carolina", ", sc"),
    # ", georgia" is normalised to ", ga" before matching, so Tbilisi arrives
    # here looking exactly like Macon. The country's cities are a short list;
    # Georgia's towns are not — so the country goes in the decoys.
    "ga-other": ("georgia", ", ga"),

    # ── International ─────────────────────────────────────────────────────
    # Bare "lagos" plus decoys, NOT a set of country-qualified patterns. The
    # first cut here country-qualified everything ("lagos, nigeria" etc.) to
    # keep Lagos Portugal and Lagos de Moreno off the board — and then missed
    # the only real Lagos posting on any board we scrape, because Workday
    # writes GE HealthCare's as "NGA05-01-Lagos-Bishop Aboyade Cole Street".
    # Real ATS location strings are too irregular to enumerate; the lookalikes
    # are not. See metro_decoys.py, and the module docstring's rule 3.
    #
    # "nigeria" is deliberately absent: Mondelez posts "Ondo, Nigeria", which
    # is a different market 200km away. Same reasoning as STATE_FALLBACK.
    "lagos-ng": ("lagos", "ikeja", "ikoyi", "lekki", "victoria island",
                 "apapa", "surulere", "yaba, lagos"),
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
    # Non-US first: every one of its patterns names a country/state or a
    # neighbourhood unique to it, so it can neither steal from a US metro nor
    # be stolen from by one.
    "lagos-ng",
    # State-qualified regionals next.
    "york-pa", "lancaster-pa", "harrisburg-pa",
    "charleston-sc", "columbia-sc", "greenville-sc", "rock-hill-sc",
    "myrtle-beach-sc", "hilton-head-sc", "sumter-sc", "florence-sc",
    "charlotte-nc", "raleigh-nc", "durham-nc", "greensboro-nc",
    "winston-salem-nc", "fayetteville-nc", "asheville-nc", "wilmington-nc",
    "hickory-nc", "greenville-nc", "jacksonville-nc", "burlington-nc",
    "new-bern-nc", "rocky-mount-nc", "goldsboro-nc",
    "augusta-ga", "savannah-ga", "columbus-ga", "macon-ga", "athens-ga",
    "gainesville-ga", "warner-robins-ga", "albany-ga", "dalton-ga",
    "valdosta-ga", "rome-ga", "brunswick-ga", "hinesville-ga",
    # Then the top 20, specific before catch-all.
    "minneapolis", "seattle", "denver", "boston", "detroit",
    "san-francisco", "riverside", "san-diego", "philadelphia-pa",
    "baltimore-md", "tampa-fl", "nyc", "miami", "chicago",
    "phoenix", "la", "dc", "atlanta", "houston", "dallas",
    # Statewide catch-alls dead last: every named metro in NC/SC/GA — and
    # every metro anywhere else — gets first refusal on the location.
    "nc-other", "sc-other", "ga-other",
)

ALL_METROS = MATCH_ORDER

assert set(MATCH_ORDER) == set(PATTERNS) == set(LABELS), (
    "MATCH_ORDER, PATTERNS and LABELS must cover exactly the same metros"
)
assert (set(TOP_20) | set(PA_REGIONAL) | set(SC_REGIONAL) | set(NC_REGIONAL)
        | set(GA_REGIONAL) | set(INTERNATIONAL)) == set(MATCH_ORDER)
assert STATEWIDE_CATCH_ALLS <= set(MATCH_ORDER)
assert set(MATCH_ORDER[-len(STATEWIDE_CATCH_ALLS):]) == STATEWIDE_CATCH_ALLS, (
    "the statewide catch-alls must be checked last, or they steal from a "
    "named metro in their own state"
)


# Bare state tokens, used ONLY when the caller already knows which metro it is
# scraping (the per-city Workday/Greenhouse lists, where a posting's location
# is sometimes just ", TX"). They are deliberately kept OUT of PATTERNS: in
# multi-metro inference a catch-all silently relabels every job in the state as
# the big metro. Before this split, dropping San Antonio turned every San
# Antonio posting into a Dallas one instead of excluding it, and "Savannah, GA"
# read as Atlanta.
# Bare abbreviations are safe here ONLY because _is_bare_state() requires that
# nothing word-like survives removing the token — "tx" alone would otherwise
# match inside ordinary text.
STATE_FALLBACK = {
    "dallas": ("texas", "tx"),
    "houston": ("texas", "tx"),
    "atlanta": ("georgia", "ga"),
    "phoenix": ("arizona", "az"),
}


# Workday and friends spell states out ("Arlington, Virginia") while the
# patterns above use postal abbreviations for disambiguation ("arlington, va").
# Normalising one to the other here means every pattern gets both spellings for
# free — without it, real DC-suburb postings were being dropped.
_STATE_ABBR = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct",
    "delaware": "de", "florida": "fl", "georgia": "ga", "hawaii": "hi",
    "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me",
    "maryland": "md", "massachusetts": "ma", "michigan": "mi",
    "minnesota": "mn", "mississippi": "ms", "missouri": "mo",
    "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm",
    "new york": "ny", "north carolina": "nc", "north dakota": "nd",
    "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd",
    "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt",
    "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy",
}
# Longest first so "west virginia" isn't eaten by "virginia".
_STATE_PAIRS = sorted(_STATE_ABBR.items(), key=lambda kv: -len(kv[0]))


def normalize_states(text):
    """Rewrite ", <state name>" as ", <abbr>" so both spellings match.

    Only touches a state name that follows a comma, so a city genuinely called
    Washington or Georgia is left alone.
    """
    for name, abbr in _STATE_PAIRS:
        text = text.replace(f", {name}", f", {abbr}")
    return text


def _is_bare_state(text, tokens):
    """True when `text` carries a state token and no actual place name.

    The fallback exists for locations like ", TX" or "Texas" — a per-city
    scrape where the posting simply didn't name a city. It must NOT fire for
    "Lubbock, TX, 79407": that names a real place we don't cover, and claiming
    it for Dallas puts a Panhandle job on the Dallas board (which is exactly
    what happened to Xcel Energy's postings before 2026-07-21).

    So: strip the state token and the zip digits, and require that nothing
    word-like is left.
    """
    import re

    for token in tokens:
        if token not in text:
            continue
        remainder = re.sub(r"[^a-z]+", " ", text.replace(token, " "))
        if not re.search(r"[a-z]{3,}", remainder):
            return True
    return False


def matches_metro(location, slug, allow_state_fallback=False):
    """Whether `location` sits in `slug`.

    `allow_state_fallback` is for per-city scraping only — see STATE_FALLBACK.
    """
    from metro_decoys import strip_decoys

    text = strip_decoys(normalize_states((location or "").lower()), slug)
    if not text:
        return False
    if any(pattern in text for pattern in PATTERNS.get(slug, ())):
        return True
    if allow_state_fallback:
        return _is_bare_state(text, STATE_FALLBACK.get(slug, ()))
    return False


def infer_metro(location, allowed=None):
    """First metro whose patterns match `location`, or "" when none do.

    `allowed` restricts the search to a subset of slugs — used by verticals
    that intentionally cover fewer metros than the full set.
    """
    from metro_decoys import strip_decoys

    text = normalize_states((location or "").lower())
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
