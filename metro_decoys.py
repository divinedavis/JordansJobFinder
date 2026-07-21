"""Place names that merely *contain* a metro's token but sit in another market.

Every city matcher in this repo is a substring test, so NYC's bare "manhattan"
happily matches "Manhattan Beach, CA" — that's how Skechers' Manhattan Beach HQ
role landed on the New York board on 2026-07-21. NYC is checked first in
PM_METROS, so it beat LA's own "manhattan beach" entry.

`strip_decoys` blanks a metro's decoys out of the location string *before* that
metro's patterns run. Later metros still see the original text, so LA keeps
matching "manhattan beach" normally.

Add a decoy here rather than reordering the metro list — ordering fixes only
work when the true metro is checked first, and that can't be true for everyone.
"""

DECOY_LOCS = {
    "nyc": (
        "manhattan beach",      # CA (Skechers HQ) and MN
        "manhattan, ks",
        "manhattan, il",
        "manhattan, mt",
        "manhattan, ne",
        "brooklyn park",        # MN
        "brooklyn center",      # MN
        "brooklyn, oh",
        "brooklyn, mi",
        "brooklyn, wi",
        "new york mills",       # MN / ME
    ),
    "atlanta": (
        "atlanta, tx",
        "atlanta, il",
        "atlanta, in",
        "new atlanta",
    ),
    "miami": (
        "miami, ok",
        "miami, az",
        "miami township",       # OH
        "miamisburg",           # OH
        "miami county",
    ),
    "dallas": (
        "dallas, ga",
        "dallas, or",
        "dallas, nc",
        "dallas, pa",
        "dallas center",        # IA
    ),
    "houston": (
        "houston, mo",
        "houston, ms",
        "houston, mn",
        "houston county",
        "houston, ak",
    ),
    "dc": (
        "washington, pa",
        "washington, mo",
        "washington, il",
        "washington, in",
        "washington, nc",
        "washington, ut",
        "washington, ia",
        "port washington",      # NY / WI
        "washington court house",   # OH
        "washington township",
        "lake washington",
        "washington state",
        "washington, wa",
        "mount washington",
    ),
    "la": (
        "los angeles, chile",
        "east los angeles county detention",
    ),
    "chicago": (
        "chicago heights, in",
        "west chicago, in",
    ),
    "phoenix": (
        "phoenix, or",
        "phoenix, il",
        "phoenix, ny",
        "phoenixville",         # PA
    ),
    "san-antonio": (
        "san antonio, nm",
        "san antonio, pr",
        "san antonio, chile",
    ),
    "san-diego": (
        "san diego, ca — remote latam",
        "san diego, chile",
    ),
    "jacksonville-fl": (
        "jacksonville, nc",
        "jacksonville, tx",
        "jacksonville, ar",
        "jacksonville, al",
        "jacksonville, il",
        "jacksonville beach, nc",
    ),
    "philadelphia-pa": (
        "philadelphia, ms",
        "philadelphia, tn",
        "philadelphia, ny",
    ),
    "boston": (
        "boston, ga",
        "boston, ky",
        "new boston",           # TX / MI / NH
        "boston spa",           # UK
        "boston, lincolnshire",  # UK
    ),
    "riverside": (
        "riverside, il",        # Chicago suburb
        "riverside, mo",
        "riverside, oh",
        "riverside, ct",
        "ontario, canada",      # vs Ontario, CA
        "ontario, on",
    ),
    "san-francisco": (
        "san francisco, cordoba",
        "oakland, nj",
        "oakland park",         # FL — Miami metro
        "oakland, md",
        "richmond, va",
        "richmond, bc",
        "san jose, costa rica",
        "san jose, ca — remote latam",
    ),
    "detroit": (
        "detroit lakes",        # MN
        "detroit, or",
        "detroit, tx",
        "detroit, al",
    ),
    "seattle": (
        "seattle, il",
    ),
    "minneapolis": (
        "minneapolis, ks",
        "minneapolis, nc",
        "st. paul, ne",
        "st. paul, ak",
    ),
    "denver": (
        "denver, pa",           # Lancaster County
        "denver, nc",
        "denver, ia",
        "denver city, tx",
        "boulder, mt",
        "boulder city",         # NV
    ),
    "tampa-fl": (
        "st. petersburg, russia",
        "lakeland, ga",
        "clearwater, mn",
        "clearwater, bc",
    ),
    "baltimore-md": (
        "baltimore, oh",
        "baltimore county, va",
        "new baltimore",        # MI / VA
    ),
    "sumter-sc": (
        "sumter county, fl",
        "sumter county, ga",
        "sumter, ga",
    ),
    "florence-sc": (
        "florence, ky",
        "florence, al",
        "florence, az",
        "florence, ms",
        "florence, or",
        "florence, italy",
    ),
    "york-pa": (
        "new york",             # the big one — "York, PA" vs "New York, NY"
        "york, sc",
        "york, ne",
        "yorktown",
        "yorkville",
    ),
    "lancaster-pa": (
        "lancaster, ca",        # LA County
        "lancaster, tx",        # Dallas County
        "lancaster, oh",
        "lancaster, ny",
        "lancaster, sc",
    ),
    "charleston-sc": (
        "charleston, wv",
        "charleston, il",
        "charleston, mo",
    ),
    "greenville-sc": (
        "greenville, nc",
        "greenville, tx",
        "greenville, ms",
        "greenville, al",
        "anderson, in",
    ),
    "columbia-sc": (
        "columbia, md",         # Baltimore metro
        "columbia, mo",
        "columbia, tn",
        "columbia, pa",         # Lancaster County
    ),
    "rock-hill-sc": (
        "rock hill, mo",
    ),
    "harrisburg-pa": (
        "harrisburg, nc",
        "harrisburg, sd",
        "harrisburg, il",
    ),
}


def strip_decoys(loc: str, code: str) -> str:
    """Return `loc` with `code`'s decoy place names blanked out.

    `loc` must already be lowercased — every caller lowercases before matching.
    """
    for decoy in DECOY_LOCS.get(code, ()):
        if decoy in loc:
            loc = loc.replace(decoy, " ")
    return loc
