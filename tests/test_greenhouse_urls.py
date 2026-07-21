"""Guards for Greenhouse "View Role" deep links.

Stripe's board hands back stripe.com/jobs/search?gh_jid=<id>. On 2026-07-21
that URL dropped the visitor on Stripe's full job index for a req the company
site hadn't published, so "View Role" was useless.
"""
import greenhouse_urls
from greenhouse_urls import EMBED_URL, greenhouse_job_url


class _Resp:
    def __init__(self, url, status_code=200):
        self.url = url
        self.status_code = status_code


def _stub_head(monkeypatch, final_url, status_code=200):
    monkeypatch.setattr(
        greenhouse_urls.requests, "head",
        lambda *a, **k: _Resp(final_url, status_code),
    )


def _clear_cache():
    greenhouse_urls._resolved.clear()


def test_greenhouse_hosted_url_passes_through(monkeypatch):
    _clear_cache()
    job = {"id": 123, "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123"}
    # No network call at all for boards that already deep-link.
    monkeypatch.setattr(greenhouse_urls.requests, "head",
                        lambda *a, **k: pytest_fail())
    assert greenhouse_job_url(job, "acme") == job["absolute_url"]


def pytest_fail():
    raise AssertionError("should not have made a request")


def test_company_site_that_resolves_the_role_is_kept(monkeypatch):
    _clear_cache()
    job = {"id": 7923047,
           "absolute_url": "https://stripe.com/jobs/search?gh_jid=7923047"}
    _stub_head(monkeypatch, "https://stripe.com/jobs/listing/program-manager/7923047")
    assert greenhouse_job_url(job, "stripe") == job["absolute_url"]


def test_company_site_that_lands_on_the_index_falls_back_to_greenhouse(monkeypatch):
    _clear_cache()
    job = {"id": 8074923,
           "absolute_url": "https://stripe.com/jobs/search?gh_jid=8074923"}
    _stub_head(monkeypatch, "https://stripe.com/jobs/search?gh_jid=8074923")
    assert greenhouse_job_url(job, "stripe") == EMBED_URL.format(
        token="stripe", job_id=8074923)


def test_dead_req_falls_back_to_greenhouse(monkeypatch):
    _clear_cache()
    job = {"id": 999, "absolute_url": "https://acme.com/jobs/search?gh_jid=999"}
    _stub_head(monkeypatch, "https://acme.com/jobs/search?gh_jid=999", 404)
    assert greenhouse_job_url(job, "acme") == EMBED_URL.format(
        token="acme", job_id=999)


def test_network_failure_keeps_the_company_url(monkeypatch):
    _clear_cache()
    job = {"id": 5, "absolute_url": "https://acme.com/jobs/search?gh_jid=5"}

    def boom(*a, **k):
        raise greenhouse_urls.requests.RequestException("timeout")

    monkeypatch.setattr(greenhouse_urls.requests, "head", boom)
    assert greenhouse_job_url(job, "acme") == job["absolute_url"]


def test_resolution_is_cached(monkeypatch):
    _clear_cache()
    job = {"id": 42, "absolute_url": "https://acme.com/jobs/search?gh_jid=42"}
    calls = []

    def counting_head(*a, **k):
        calls.append(1)
        return _Resp("https://acme.com/jobs/listing/x/42")

    monkeypatch.setattr(greenhouse_urls.requests, "head", counting_head)
    greenhouse_job_url(job, "acme")
    greenhouse_job_url(job, "acme")
    assert len(calls) == 1
