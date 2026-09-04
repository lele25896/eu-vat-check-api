"""Normalization, format regexes, and VIES error mapping are pure/offline
testable via monkeypatching app.vies._fetch — the actual live VIES call is
exercised once via the API in test_api.py.
"""
import urllib.error

import pytest

from app import vies
from app.vies import VatError, ViesError, check_vat, normalize_vat, validate, vies_status


@pytest.mark.parametrize(
    "raw,country,expected",
    [
        ("it 12345678901", None, ("IT", "12345678901")),
        ("DE-123456789", None, ("DE", "123456789")),
        ("GR123456789", None, ("EL", "123456789")),
        ("ATU12345678", None, ("AT", "U12345678")),
        ("XI123456789", None, ("XI", "123456789")),
        ("6388047V", "IE", ("IE", "6388047V")),
        ("  ie6388047v  ", None, ("IE", "6388047V")),
    ],
)
def test_normalize_vat(raw, country, expected):
    assert normalize_vat(raw, country) == expected


@pytest.mark.parametrize("raw", ["ZZ1", "", "ZZ"])
def test_normalize_vat_rejects_bad_country(raw):
    with pytest.raises(VatError):
        normalize_vat(raw)


@pytest.mark.parametrize(
    "cc,number,valid",
    [
        ("IE", "6388047V", True),
        ("IE", "123", False),
        ("DE", "123456789", True),
        ("DE", "12345", False),
        ("IT", "12345678901", True),
        ("AT", "U12345678", True),
        ("AT", "12345678", False),
        ("NL", "123456789B01", True),
        ("FR", "AB123456789", True),
        ("XI", "GD123", True),
    ],
)
def test_format_regex(cc, number, valid):
    assert bool(vies.FORMATS[cc].match(number)) is valid


def _patch_fetch(monkeypatch, payload):
    monkeypatch.setattr(vies, "_fetch", lambda url: payload)


def test_check_vat_valid(monkeypatch):
    _patch_fetch(monkeypatch, {"isValid": True, "userError": "VALID", "name": "GOOGLE IRELAND LIMITED", "address": "DUBLIN"})
    result = check_vat("IE", "6388047V")
    assert result == {"valid": True, "name": "GOOGLE IRELAND LIMITED", "address": "DUBLIN"}


def test_check_vat_invalid(monkeypatch):
    _patch_fetch(monkeypatch, {"isValid": False, "userError": "INVALID", "name": "---", "address": "---"})
    result = check_vat("IE", "0000000V")
    assert result == {"valid": False, "name": None, "address": None}


def test_check_vat_invalid_input(monkeypatch):
    _patch_fetch(monkeypatch, {"userError": "INVALID_INPUT"})
    with pytest.raises(ViesError) as exc:
        check_vat("IE", "6388047V")
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "code",
    ["MS_UNAVAILABLE", "SERVICE_UNAVAILABLE", "TIMEOUT", "MS_MAX_CONCURRENT_REQ", "GLOBAL_MAX_CONCURRENT_REQ"],
)
def test_check_vat_retryable_errors(monkeypatch, code):
    _patch_fetch(monkeypatch, {"userError": code})
    with pytest.raises(ViesError) as exc:
        check_vat("IE", "6388047V")
    assert exc.value.status_code == 503
    assert exc.value.payload["retryable"] is True


def test_check_vat_unknown_error_maps_to_502(monkeypatch):
    _patch_fetch(monkeypatch, {"userError": "SOME_NEW_CODE_VIES_ADDED_LATER"})
    with pytest.raises(ViesError) as exc:
        check_vat("IE", "6388047V")
    assert exc.value.status_code == 502


def test_fetch_http_4xx_is_non_retryable(monkeypatch):
    def _raise(url, timeout=10):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(vies.urllib.request, "urlopen", _raise)
    with pytest.raises(ViesError) as exc:
        vies._fetch("http://example.com")
    assert exc.value.status_code == 502
    assert exc.value.payload["error"] == "VIES_HTTP_404"
    assert "retryable" not in exc.value.payload


def test_fetch_http_5xx_is_retryable(monkeypatch):
    def _raise(url, timeout=10):
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", None, None)

    monkeypatch.setattr(vies.urllib.request, "urlopen", _raise)
    with pytest.raises(ViesError) as exc:
        vies._fetch("http://example.com")
    assert exc.value.status_code == 503
    assert exc.value.payload["retryable"] is True


def test_vies_status(monkeypatch):
    _patch_fetch(
        monkeypatch,
        {"vow": {"available": True}, "countries": [{"countryCode": "DE", "availability": "Unavailable"}, {"countryCode": "IT", "availability": "Available"}]},
    )
    result = vies_status()
    assert result == {"vies_available": True, "countries": {"DE": "Unavailable", "IT": "Available"}}


def test_validate_format_invalid_skips_vies_call(monkeypatch):
    def _boom(url):
        raise AssertionError("should not call VIES for a format-invalid number")

    monkeypatch.setattr(vies, "_fetch", _boom)
    result = validate("IE123")
    assert result["format_valid"] is False
    assert result["valid"] is False
    assert result["name"] is None
