# EU VAT Number Checker

Single-call API: validates an EU VAT number against the official
[VIES](https://ec.europa.eu/taxation_customs/vies/) service and returns the
registered company name/address, plus a `/status` endpoint for per-country
VIES availability (member-state outages are common — that's the whole
reason `/status` earns its place). Same deploy pattern as
[SSL & Site Health Monitor](https://github.com/lele25896/ssl-site-health-api)
(FastAPI + Docker + Terraform + GitHub Actions CI/CD with Workload Identity
Federation) — stdlib-only checker, no new deps beyond fastapi/uvicorn.

## Setup

```
pip install -r requirements-dev.txt
```

## Run

```
uvicorn app.main:app --reload
```

- `GET /health` — liveness
- `GET /validate?vat=IE6388047V` (also `?vat=6388047V&country=IE`) —
  ```json
  {
    "vat": "IE6388047V",
    "country_code": "IE",
    "vat_number": "6388047V",
    "format_valid": true,
    "valid": true,
    "name": "GOOGLE IRELAND LIMITED",
    "address": "3RD FLOOR, GORDON HOUSE, BARROW STREET, DUBLIN 4",
    "checked_at": "2026-09-04T10:00:00Z",
    "source": "VIES"
  }
  ```
  A format-invalid number returns 200 with `format_valid:false` (no VIES
  call spent) — a checkout form wants a yes/no, not an HTTP error. Unknown
  country / empty input → 400. VIES down/timeout for that country → 503
  with `Retry-After: 30` — no server-side retries, VIES has undocumented
  per-IP throttling.
- `GET /status` — `{"vies_available": true, "countries": {"DE": "Unavailable", ...}}`

No UK (GB) support — HMRC runs a separate API, out of scope.

## Test

```
pytest tests/
```

`tests/test_vies.py` covers normalization, format regexes, and VIES
error-code mapping offline (monkeypatched fetch). `tests/test_api.py` hits
the real VIES service (`IE 6388047V` = Google Ireland, this bet's
`example.com`) — skips rather than fails if VIES itself is down during the
run.

## Deploy (manual, once)

```
gcloud projects create PROJECT_ID
gcloud config set project PROJECT_ID
# link billing in the console, then:
gcloud services enable run.googleapis.com artifactregistry.googleapis.com monitoring.googleapis.com iamcredentials.googleapis.com cloudresourcemanager.googleapis.com
gsutil mb -l europe-west1 gs://eu-vat-check-tfstate
gcloud artifacts repositories create eu-vat-check-api --repository-format=docker --location=europe-west1
gcloud auth configure-docker europe-west1-docker.pkg.dev
docker build -t europe-west1-docker.pkg.dev/PROJECT_ID/eu-vat-check-api/eu-vat-check-api:latest .
docker push europe-west1-docker.pkg.dev/PROJECT_ID/eu-vat-check-api/eu-vat-check-api:latest
gcloud run deploy eu-vat-check-api --image europe-west1-docker.pkg.dev/PROJECT_ID/eu-vat-check-api/eu-vat-check-api:latest --region europe-west1 --allow-unauthenticated --memory 256Mi --max-instances 2
```

Then set `terraform/terraform.tfvars` `project_id`, `terraform import` the
manually-created resources, and wire repo secrets `WIF_PROVIDER`,
`WIF_SERVICE_ACCOUNT`, `GCP_PROJECT_ID` for CI.

## CV line

> Deployed a stdlib-only EU VAT number validator (VIES REST wrapper) as a
> containerized FastAPI REST service on **GCP Cloud Run**, with
> **GitHub Actions CI/CD** and **Terraform** IaC. Free-tier cost (~€0).
