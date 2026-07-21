"""Guards for Greenhouse "View Role" deep links.

Stripe's board hands back stripe.com/jobs/search?gh_jid=<id>. On 2026-07-21
that URL dropped the visitor on Stripe's full job index for a req the company
site hadn't published, so "View Role" was useless.

The fallback must stay conservative: the company's own page beats Greenhouse's
bare application form, so we only abandon it on positive proof it doesn't
resolve. A 403 from the droplet is a WAF, not a dead posting.
"""
import pytest

import greenhouse_urls
from greenhouse_urls import EMBED_URL, greenhouse_job_url


class _Resp:
    def __init__(self, url, status_code=200):
        self.url = url
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _clear_cache():
    greenhouse_urls._resolved.clear()
    yield
    greenhouse_urls._resolved.clear()


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if a case makes a request it shouldn't."""
    def boom(*a, **k):
        raise AssertionError("should not have made a request")
    monkeypatch.setattr(greenhouse_urls.requests, "head", boom)


def _stub_head(monkeypatch, final_url, status_code=200):
    monkeypatch.setattr(
        greenhouse_urls.requests, "head",
        lambda *a, **k: _Resp(final_url, status_code),
    )


# ── URLs that need no verification ────────────────────────────────────────────

def test_greenhouse_hosted_url_passes_through(no_network):
    job = {"id": 7921821,
           "absolute_url": "https://boards.greenhouse.io/justworks/jobs/7921821?gh_jid=7921821"}
    assert greenhouse_job_url(job, "justworks") == job["absolute_url"]


def test_company_url_with_id_in_path_passes_through(no_network):
    # Okta: .../opportunity/7607493?gh_jid=7607493 already deep-links.
    job = {"id": 7607493,
           "absolute_url": "https://www.okta.com/company/careers/opportunity/7607493?gh_jid=7607493"}
    assert greenhouse_job_url(job, "okta") == job["absolute_url"]


def test_url_without_gh_jid_passes_through(no_network):
    job = {"id": 123, "absolute_url": "https://acme.com/careers/pm-role"}
    assert greenhouse_job_url(job, "acme") == job["absolute_url"]


# ── Ambiguous query-only URLs get verified ────────────────────────────────────

def test_company_site_that_resolves_the_role_is_kept(monkeypatch):
    job = {"id": 7923047,
           "absolute_url": "https://stripe.com/jobs/search?gh_jid=7923047"}
    _stub_head(monkeypatch, "https://stripe.com/jobs/listing/program-manager/7923047")
    assert greenhouse_job_url(job, "stripe") == job["absolute_url"]


def test_company_site_that_never_moves_falls_back(monkeypatch):
    """Stripe's unpublished req: no redirect fires, we sit on /jobs/search."""
    job = {"id": 8074923,
           "absolute_url": "https://stripe.com/jobs/search?gh_jid=8074923"}
    _stub_head(monkeypatch, "https://stripe.com/jobs/search?gh_jid=8074923")
    assert greenhouse_job_url(job, "stripe") == EMBED_URL.format(
        token="stripe", job_id="8074923")


def test_redirect_to_a_generic_careers_page_falls_back(monkeypatch):
    """Squarespace bounces to /about/careers and drops gh_jid entirely."""
    job = {"id": 8014027,
           "absolute_url": "https://www.squarespace.com/about/careers/jobs?gh_jid=8014027"}
    _stub_head(monkeypatch, "https://www.squarespace.com/about/careers")
    assert greenhouse_job_url(job, "squarespace") == EMBED_URL.format(
        token="squarespace", job_id="8014027")


def test_slugged_job_page_keeping_the_id_in_the_query_is_kept(monkeypatch):
    """FanDuel deep-links to a slug and leaves the id in the query, not path."""
    job = {"id": 7642788,
           "absolute_url": "https://www.fanduel.careers/jobs?gh_jid=7642788"}
    _stub_head(
        monkeypatch,
        "https://www.fanduel.careers/jobs/fanduel/lead-product-manager-payments-2/?gh_jid=7642788",
    )
    assert greenhouse_job_url(job, "fanduel") == job["absolute_url"]


# ── Never infer death from a blocked probe ────────────────────────────────────

@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
def test_error_status_keeps_the_company_url(monkeypatch, status):
    """A WAF blocking the droplet must not cost us the company's own page."""
    job = {"id": 7280325,
           "absolute_url": "https://www.mongodb.com/careers/job/?gh_jid=7280325"}
    _stub_head(monkeypatch, job["absolute_url"], status)
    assert greenhouse_job_url(job, "mongodb") == job["absolute_url"]


def test_network_failure_keeps_the_company_url(monkeypatch):
    job = {"id": 5, "absolute_url": "https://acme.com/jobs/search?gh_jid=5"}

    def boom(*a, **k):
        raise greenhouse_urls.requests.RequestException("timeout")

    monkeypatch.setattr(greenhouse_urls.requests, "head", boom)
    assert greenhouse_job_url(job, "acme") == job["absolute_url"]


def test_resolution_is_cached(monkeypatch):
    job = {"id": 42, "absolute_url": "https://acme.com/jobs/search?gh_jid=42"}
    calls = []

    def counting_head(*a, **k):
        calls.append(1)
        return _Resp("https://acme.com/jobs/listing/x/42")

    monkeypatch.setattr(greenhouse_urls.requests, "head", counting_head)
    greenhouse_job_url(job, "acme")
    greenhouse_job_url(job, "acme")
    assert len(calls) == 1
