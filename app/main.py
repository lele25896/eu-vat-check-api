import os
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from app.vies import VatError, ViesError, validate, vies_status

app = FastAPI(
    title="EU VAT Number Checker",
    description=(
        "Validates EU VAT numbers against the official VIES service and "
        "returns the registered company name/address. `/status` reports "
        "per-country VIES availability — member-state outages are common, "
        "check it before treating a failed validation as invalid. "
        "No UK (GB) support — HMRC runs a separate API, out of scope."
    ),
)

# Set on the Cloud Run service once wired into RapidAPI (Studio > Security
# tab). Unset = check disabled, so local dev/tests hit endpoints unauthenticated.
RAPIDAPI_PROXY_SECRET = os.environ.get("RAPIDAPI_PROXY_SECRET")


def _check_proxy_secret(x_rapidapi_proxy_secret: str | None) -> None:
    if RAPIDAPI_PROXY_SECRET and not (
        x_rapidapi_proxy_secret
        and secrets.compare_digest(x_rapidapi_proxy_secret, RAPIDAPI_PROXY_SECRET)
    ):
        raise HTTPException(403, "missing or invalid proxy secret")


def _vies_error_response(e: ViesError) -> JSONResponse:
    headers = {"Retry-After": "30"} if e.status_code == 503 else {}
    return JSONResponse(status_code=e.status_code, content=e.payload, headers=headers)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get(
    "/validate",
    summary="Validate an EU VAT number",
    description="Accepts `vat` with an inline country prefix (`IE6388047V`) "
    "or a bare number plus `country` (`vat=6388047V&country=IE`). Format "
    "errors return 200 with `format_valid:false` (no VIES call, no quota "
    "spent) — a checkout form wants a yes/no, not an HTTP error.",
    responses={
        400: {"description": "Unknown country code or empty VAT number"},
        503: {"description": "VIES unavailable/timed out for this country — retry after `Retry-After` seconds"},
    },
)
def validate_endpoint(
    vat: str,
    country: str | None = None,
    x_rapidapi_proxy_secret: str | None = Header(default=None),
):
    _check_proxy_secret(x_rapidapi_proxy_secret)
    try:
        return validate(vat, country)
    except VatError as e:
        raise HTTPException(400, str(e))
    except ViesError as e:
        return _vies_error_response(e)


@app.get(
    "/status",
    summary="VIES per-country availability",
    description="VIES member states go down independently and often — "
    "check this before assuming a failed /validate call means an invalid VAT.",
    responses={503: {"description": "VIES status endpoint itself unreachable"}},
)
def status_endpoint(x_rapidapi_proxy_secret: str | None = Header(default=None)):
    _check_proxy_secret(x_rapidapi_proxy_secret)
    try:
        return vies_status()
    except ViesError as e:
        return _vies_error_response(e)
