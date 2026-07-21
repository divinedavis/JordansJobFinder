"""Turn a Greenhouse board entry into a link that actually opens the role.

Greenhouse's `absolute_url` points at the company's own careers site when the
board is configured with a redirect — Stripe hands back
`https://stripe.com/jobs/search?gh_jid=<id>`. That only deep-links while the
company's site publishes that particular req. When it doesn't, the visitor is
dumped on the full job index with no way to find the posting (2026-07-21:
Stripe's "Consumer Operations, Program Manager" was live on the Greenhouse API
but absent from stripe.com/jobs, so "View Role" opened the whole board).

`greenhouse_job_url` follows the redirect once with a cheap HEAD. If the site
resolves the req we keep the company-hosted page; otherwise we fall back to
Greenhouse's own hosted application page, which always renders the specific
role. Results are cached per process so a board's jobs cost one HEAD each at
most, and any network trouble falls back to the original URL.
"""

from urllib.parse import urlsplit

import requests

EMBED_URL = "https://boards.greenhouse.io/embed/job_app?for={token}&token={job_id}"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TIMEOUT = 10
_resolved: dict = {}

# Final paths that mean "you landed on the index, not the job". Company career
# sites use these for the searchable board itself.
_INDEX_PATHS = ("", "/jobs", "/jobs/search", "/careers", "/careers/search",
                "/en/jobs", "/en/careers")


def _is_index(url: str) -> bool:
    return urlsplit(url).path.rstrip("/").lower() in _INDEX_PATHS


def greenhouse_job_url(job: dict, token: str) -> str:
    """Best link for a Greenhouse job dict, deep-link verified when needed."""
    absolute = (job.get("absolute_url") or "").strip()
    job_id = job.get("id") or job.get("internal_job_id") or ""
    embed = EMBED_URL.format(token=token, job_id=job_id) if job_id else ""

    if not absolute:
        return embed
    # Greenhouse-hosted boards already link straight at the job.
    if "gh_jid=" not in absolute:
        return absolute
    if not embed:
        return absolute

    cached = _resolved.get(absolute)
    if cached is not None:
        return cached

    resolved = absolute
    try:
        resp = requests.head(
            absolute,
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
            allow_redirects=True,
        )
        # Still sitting on the board index (or the req is gone) → use the
        # Greenhouse-hosted page, which names the role and takes applications.
        if resp.status_code >= 400 or _is_index(resp.url):
            resolved = embed
    except requests.RequestException:
        pass  # network hiccup — keep the company URL rather than guess

    _resolved[absolute] = resolved
    return resolved
