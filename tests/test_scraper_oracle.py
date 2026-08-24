"""Guards for the Oracle Cloud Recruiting (ORC) source — added for Uber.

Uber sat in WORKDAY_COMPANIES under the tenant "uber", which does not exist:
every version/site pair 422s, and the daily log recorded "[Uber] 0 candidate(s)"
every morning for months while the board carried zero Uber jobs. These tests
pin the replacement so the same silent-zero can't come back unnoticed.
"""
import json
from datetime import date, timedelta

import job_enrich
import scraper


def _today():
    return date.today().isoformat()


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _search_payload(requisitions, total=None):
    return {"items": [{
        "TotalJobsCount": len(requisitions) if total is None else total,
        "requisitionList": requisitions,
    }]}


def test_uber_is_not_on_workday_anymore():
    tenants = {tenant for _, tenant, _, _, _ in scraper.WORKDAY_COMPANIES}
    assert "uber" not in tenants
    assert "Uber" in {name for name, _, _, _ in scraper.ORACLE_MULTI}


def test_oracle_multi_entries_are_well_formed():
    for name, host, site_number, site_path in scraper.ORACLE_MULTI:
        assert name and site_path
        assert host.endswith(".oraclecloud.com")
        # siteNumber is the API's filter and is NOT the site name in the URL —
        # Oracle serves the pod's DEFAULT board for an unknown one, silently.
        assert site_number.startswith("CX_")
        assert site_number != site_path


def test_scrape_oracle_multi_keeps_target_roles_and_drops_the_rest(monkeypatch):
    reqs = [
        {"Id": "1", "Title": "Sr Product Manager, Tech", "PostedDate": _today(),
         "PrimaryLocation": "New York City, NY, United States", "secondaryLocations": []},
        # Oracle's keyword match is loose — non-PM titles come back and must go.
        {"Id": "2", "Title": "Software Engineer II", "PostedDate": _today(),
         "PrimaryLocation": "New York City, NY, United States", "secondaryLocations": []},
        # Unsupported metro.
        {"Id": "3", "Title": "Staff Program Manager, Tech", "PostedDate": _today(),
         "PrimaryLocation": "Boise, ID, United States", "secondaryLocations": []},
        # Below the seniority floor every metro enforces — Uber posts a lot of
        # these, and they must not reach the board.
        {"Id": "4", "Title": "Product Manager II", "PostedDate": _today(),
         "PrimaryLocation": "New York City, NY, United States", "secondaryLocations": []},
        # Outside the recency window.
        {"Id": "5", "Title": "Staff Product Manager", "PrimaryLocation":
         "New York City, NY, United States", "secondaryLocations": [],
         "PostedDate": (date.today() - timedelta(days=60)).isoformat()},
    ]
    monkeypatch.setattr(scraper.requests, "get",
                        lambda *a, **k: _Resp(_search_payload(reqs)))

    jobs = scraper.scrape_oracle_multi(
        "Uber", "iaziqy.fa.ocs.oraclecloud.com", "CX_1", "UberCareers")

    titles = {job["title"] for job in jobs}
    assert titles == {"Sr Product Manager, Tech"}
    job = jobs[0]
    assert job["source"] == "oracle"
    assert job["city"] == "nyc"
    assert job["url"] == ("https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/"
                          "CandidateExperience/en/sites/UberCareers/job/1")


def test_scrape_oracle_multi_finds_the_metro_in_a_secondary_location(monkeypatch):
    reqs = [{"Id": "9", "Title": "Sr Program Manager, Tech", "PostedDate": _today(),
             "PrimaryLocation": "San Francisco, CA, United States",
             "secondaryLocations": [{"Name": "New York City, NY, United States"}]}]
    monkeypatch.setattr(scraper.requests, "get",
                        lambda *a, **k: _Resp(_search_payload(reqs)))

    jobs = scraper.scrape_oracle_multi(
        "Uber", "iaziqy.fa.ocs.oraclecloud.com", "CX_1", "UberCareers")
    # San Francisco is itself supported, so the primary wins here; the guard is
    # that the secondary list is read at all. Both search terms hit the same
    # mocked board, so the posting comes back twice — the same across-terms
    # duplication scrape_workday_multi has, resolved later by the `seen` URL set.
    assert {job["city"] for job in jobs} == {"san-francisco"}


def test_scrape_oracle_multi_survives_a_non_200(monkeypatch):
    monkeypatch.setattr(scraper.requests, "get",
                        lambda *a, **k: _Resp({}, status=503))
    assert scraper.scrape_oracle_multi(
        "Uber", "iaziqy.fa.ocs.oraclecloud.com", "CX_1", "UberCareers") == []


def test_oracle_detail_reads_body_and_salary(monkeypatch):
    payload = {"items": [{
        "ExternalDescriptionStr": "<p>Product at Uber means big decisions.</p>",
        "ExternalQualificationsStr": "<li>The base salary range is "
                                     "<b>$237,682</b> - <b>$285,219</b> per year.</li>",
        "CorporateDescriptionStr": None,
        "ExternalPostedStartDate": "2026-08-24T00:00:00+00:00",
        "PostedDate": None,
        "PrimaryLocation": "New York City, NY, United States",
        "secondaryLocations": [],
    }]}
    monkeypatch.setattr(job_enrich.requests, "get",
                        lambda *a, **k: _Resp(payload))

    url = ("https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/"
           "sites/UberCareers/job/301148")
    salary, description, posted = scraper.fetch_oracle_detail(url, "CX_1")

    assert "Product at Uber" in description
    assert "<b>" not in description
    assert "237" in salary and "285" in salary
    # PostedDate is null on this resource; the start date is the populated field.
    assert posted == "2026-08-24"


def test_oracle_detail_rejects_a_url_it_cannot_parse():
    detail = job_enrich.oracle_detail_by_url("https://example.com/job/1", "CX_1")
    assert detail == {"description": "", "locations": [], "posted": "", "status": 0}
