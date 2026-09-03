"""API contract test. Live tests hit the real VIES service (this API's whole
job is a live VIES lookup — there's nothing meaningful to mock) — CI runners
have outbound internet, same assumption the deployed service depends on. If
VIES itself is down we skip rather than go red — that's Brussels, not us.
"""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_validate_known_vat():
    r = client.get("/validate", params={"vat": "IE6388047V"})
    if r.status_code == 503:
        pytest.skip(f"VIES unavailable: {r.json()}")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert "GOOGLE" in body["name"]


def test_validate_format_invalid():
    r = client.get("/validate", params={"vat": "IE123"})
    assert r.status_code == 200
    assert r.json()["format_valid"] is False


def test_validate_unknown_country():
    r = client.get("/validate", params={"vat": "ZZ1"})
    assert r.status_code == 400


def test_status():
    r = client.get("/status")
    if r.status_code == 503:
        pytest.skip(f"VIES status endpoint unavailable: {r.json()}")
    assert r.status_code == 200
    assert "IT" in r.json()["countries"]


def test_validate_requires_proxy_secret_when_configured(monkeypatch):
    monkeypatch.setattr(main, "RAPIDAPI_PROXY_SECRET", "s3cret")

    r = client.get("/validate", params={"vat": "IE6388047V"})
    assert r.status_code == 403

    r = client.get(
        "/validate",
        params={"vat": "IE6388047V"},
        headers={"X-RapidAPI-Proxy-Secret": "wrong"},
    )
    assert r.status_code == 403

    r = client.get(
        "/validate",
        params={"vat": "IE6388047V"},
        headers={"X-RapidAPI-Proxy-Secret": "s3cret"},
    )
    assert r.status_code in (200, 503)
