import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

VIES_BASE = "https://ec.europa.eu/taxation_customs/vies/rest-api"

# VIES FAQ Q11 local-number formats, 27 EU states + XI (Northern Ireland).
# ponytail: approximate patterns (catch obviously-wrong input before it
# burns a VIES call / our egress IP reputation) — VIES itself is the
# authority on exact validity, this is just a cheap prefilter.
FORMATS = {
    "AT": re.compile(r"^U\d{8}$"),
    "BE": re.compile(r"^[01]\d{9}$"),
    "BG": re.compile(r"^\d{9,10}$"),
    "CY": re.compile(r"^\d{8}[A-Z]$"),
    "CZ": re.compile(r"^\d{8,10}$"),
    "DE": re.compile(r"^\d{9}$"),
    "DK": re.compile(r"^\d{8}$"),
    "EE": re.compile(r"^\d{9}$"),
    "EL": re.compile(r"^\d{9}$"),
    "ES": re.compile(r"^[A-Z0-9]\d{7}[A-Z0-9]$"),
    "FI": re.compile(r"^\d{8}$"),
    "FR": re.compile(r"^[A-Z0-9]{2}\d{9}$"),
    "HR": re.compile(r"^\d{11}$"),
    "HU": re.compile(r"^\d{8}$"),
    "IE": re.compile(r"^\d{7}[A-Z]{1,2}$|^\d[A-Z+*]\d{5}[A-Z]$"),
    "IT": re.compile(r"^\d{11}$"),
    "LT": re.compile(r"^(\d{9}|\d{12})$"),
    "LU": re.compile(r"^\d{8}$"),
    "LV": re.compile(r"^\d{11}$"),
    "MT": re.compile(r"^\d{8}$"),
    "NL": re.compile(r"^\d{9}B\d{2}$"),
    "PL": re.compile(r"^\d{10}$"),
    "PT": re.compile(r"^\d{9}$"),
    "RO": re.compile(r"^\d{2,10}$"),
    "SE": re.compile(r"^\d{12}$"),
    "SI": re.compile(r"^\d{8}$"),
    "SK": re.compile(r"^\d{10}$"),
    "XI": re.compile(r"^(\d{9}|\d{12}|GD\d{3}|HA\d{3})$"),
}

# 5xx / transient VIES conditions — safe to tell the client to retry.
RETRYABLE_ERRORS = {
    "MS_UNAVAILABLE",
    "SERVICE_UNAVAILABLE",
    "TIMEOUT",
    "MS_MAX_CONCURRENT_REQ",
    "GLOBAL_MAX_CONCURRENT_REQ",
}


class VatError(Exception):
    """Bad input — unknown country code or empty number. Maps to 400."""


class ViesError(Exception):
    """VIES call failed or returned an error userError code."""

    def __init__(self, status_code: int, payload: dict):
        super().__init__(payload.get("error", "vies error"))
        self.status_code = status_code
        self.payload = payload


def normalize_vat(raw: str, country: str | None = None) -> tuple[str, str]:
    if not raw:
        raise VatError("empty VAT number")
    clean = re.sub(r"[\s.\-]", "", raw).upper()
    if country:
        cc, number = country.upper(), clean
    else:
        cc, number = clean[:2], clean[2:]
    cc = "EL" if cc == "GR" else cc
    if cc not in FORMATS:
        raise VatError(f"unknown country code: {cc}")
    if not number:
        raise VatError("empty VAT number")
    return cc, number


def _fetch(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            raise ViesError(502, {"error": f"VIES_HTTP_{e.code}"})
        raise ViesError(
            503, {"error": "SERVICE_UNAVAILABLE", "retryable": True}
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise ViesError(
            503, {"error": "SERVICE_UNAVAILABLE", "retryable": True}
        )


def check_vat(cc: str, number: str) -> dict:
    try:
        data = _fetch(f"{VIES_BASE}/ms/{cc}/vat/{number}")
    except ViesError as e:
        e.payload["country_code"] = cc
        raise

    user_error = data.get("userError")
    if user_error in (None, "VALID", "INVALID"):
        name = data.get("name")
        address = data.get("address")
        return {
            "valid": bool(data.get("isValid")),
            "name": None if name in (None, "---") else name,
            "address": None if address in (None, "---") else address,
        }
    if user_error == "INVALID_INPUT":
        raise ViesError(400, {"error": user_error, "country_code": cc})
    if user_error in RETRYABLE_ERRORS:
        raise ViesError(
            503, {"error": user_error, "country_code": cc, "retryable": True}
        )
    raise ViesError(502, {"error": user_error, "country_code": cc})


def vies_status() -> dict:
    data = _fetch(f"{VIES_BASE}/check-status")
    countries = {
        c["countryCode"]: c["availability"]
        for c in data.get("countries", [])
        if c.get("countryCode") and c.get("availability")
    }
    return {
        "vies_available": bool(data.get("vow", {}).get("available", False)),
        "countries": countries,
    }


def validate(raw_vat: str, country: str | None = None) -> dict:
    cc, number = normalize_vat(raw_vat, country)
    format_valid = bool(FORMATS[cc].match(number))
    result = {
        "vat": f"{cc}{number}",
        "country_code": cc,
        "vat_number": number,
        "format_valid": format_valid,
        "valid": False,
        "name": None,
        "address": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "VIES",
    }
    if not format_valid:
        return result
    vies_result = check_vat(cc, number)
    result.update(vies_result)
    return result
