"""Unit tests for FastAPI endpoints, strict schemas, SSRF allow-list, and rate limits."""
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import fetcher

client = TestClient(app)


def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "NASA/IPAC IRSA" in resp.json()["attribution"]


def test_ssrf_allow_list_blocks_internal_and_unknown_hosts():
    with pytest.raises(fetcher.SSRFError):
        fetcher.validate_url("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(fetcher.SSRFError):
        fetcher.validate_url("https://malicious-astronomy-site.com/data")

    # Allowed host passes
    parsed = fetcher.validate_url("https://irsa.ipac.caltech.edu/TAP/sync")
    assert parsed.hostname == "irsa.ipac.caltech.edu"


def test_strict_schema_validation():
    # Out of range RA
    resp = client.post("/api/search", json={"ra": 400.0, "dec": 0.0})
    assert resp.status_code == 422

    # Malicious injection in object name
    resp = client.post("/api/resolve", json={"name": "<script>alert(1)</script>"})
    assert resp.status_code == 422


def test_job_request_color_flag():
    from backend.app import schemas

    assert schemas.JobRequest(ra=10.0, dec=20.0).color is False
    assert schemas.JobRequest(ra=10.0, dec=20.0, color=True).color is True

    resp = client.post("/api/jobs", json={"ra": 10.0, "dec": 20.0, "color": "banana"})
    assert resp.status_code == 422
