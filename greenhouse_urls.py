"""Turn a Greenhouse board entry into a link that actually opens the role.

Greenhouse's `absolute_url` points at the company's own careers site when the
board is configured with a redirect — Stripe hands back
`https://stripe.com/jobs/search?gh_jid=<id>`. That deep-links only while the
company's site publishes that particular req. When it doesn't, the visitor is
dumped on the full job index with no way to find the posting (2026-07-21:
Stripe's "Consumer Operations, Program Manager" was live on the Greenhouse API
but absent from stripe.com/jobs, so "View Role" opened the whole board).

The rule here is deliberately conservative — the company's own page is nicer
than Greenhouse's bare application form, so we only walk away from it on
positive proof that it doesn't resolve:

* URLs already on greenhouse.io are the hosted page — keep, no request.
* URLs carrying the job id in the PATH already deep-link — keep, no request.
* Otherwise the id is query-only and ambiguous, so HEAD it once: if the final
  URL's path picked up the job id, the site resolved the req and we keep it.
* Anything else — 4xx, 5xx, timeouts, connection errors — keeps the original
  URL. Several of these career sites WAF-block HEAD from a datacenter IP while
  serving browsers fine (see the probe recipe in CLAUDE.md), so a bad status is
  not evidence the posting is gone.
"""

from urllib.parse import urlsplit

import requests

EMBED_URL = "https://boards.greenhouse.io/embed/job_app?for={token}&token={job_id}"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TIMEOUT = 10
_resolved: dict = {}


def _verdict(final_url, original_path, job_id, absolute, embed):
    """Did the company site actually route us to this specific role?

    The whole redirect scheme works by the site bouncing `?gh_jid=<id>` to the
    posting, so what happened to the URL tells us whether the req resolved:

    * id landed in the path — routed to the job (Stripe, Databricks). Keep.
    * gh_jid dropped entirely — bounced to a generic careers page
      (Squarespace → /about/careers). Fall back.
    * path changed but kept gh_jid — routed to a slugged job page that carries
      the id in the query instead (FanDuel). Keep.
    * nothing moved at all — the site never resolved the req and we're sitting
      on its search page (Stripe's unpublished req). Fall back.
    """
    final = urlsplit(final_url)
    if job_id in final.path:
        return absolute
    if "gh_jid=" not in final_url:
        return embed
    if final.path != original_path:
        return absolute
    return embed


def greenhouse_job_url(job: dict, token: str) -> str:
    """Best link for a Greenhouse job dict, deep-link verified when ambiguous."""
    absolute = (job.get("absolute_url") or "").strip()
    job_id = str(job.get("id") or job.get("internal_job_id") or "")
    embed = EMBED_URL.format(token=token, job_id=job_id) if job_id else ""

    if not absolute:
        return embed
    if not embed:
        return absolute

    parts = urlsplit(absolute)
    # Greenhouse's own hosted board — already the job page.
    if parts.netloc.lower().endswith("greenhouse.io"):
        return absolute
    # Company site with the req id in the path (Okta, Lever-style) — deep link.
    if job_id in parts.path:
        return absolute
    # No gh_jid at all means the board isn't using the redirect scheme.
    if "gh_jid=" not in absolute:
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
        if resp.status_code < 400:
            resolved = _verdict(resp.url, parts.path, job_id, absolute, embed)
    except requests.RequestException:
        pass  # network hiccup or WAF — keep the company URL rather than guess

    _resolved[absolute] = resolved
    return resolved
