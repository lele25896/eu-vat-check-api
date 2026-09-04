# Pre-deploy status — EU VAT Number Checker

Running log, read this first when resuming. Plan: `../BET2-EU-VAT-PLAN.md`.

## Phase 0 — done 2026-09-04

Evidence gathered (Firecrawl scrape of RapidAPI hub + a direct-competitor
pricing page). 4 live RapidAPI competitors found (noecis $0/$18/$30/$60,
spino01 $0/$1.49/$4.99/$14.99, futureapi $0/$4.99/$9.99/$39.99, abstract-api
big-platform bundle); `lokaalsucces` listing from the plan's candidate list
is dead (404, delisted). Non-RapidAPI market context (taxid.dev comparison
page) confirmed format-precheck-before-quota and VIES-downtime-vs-invalid
distinction are real, valued differentiators — both already in this bet's
design. **Gate: Gabriele said go, keep default pricing** ($0 free 15/day →
$4.99 Pro 3,000/mo → $9.99 Ultra 15,000/mo).

## Phase 1 — in progress 2026-09-04

- Repo scaffolded at `eu-vat-check-api/`, copying `ssl-site-health-api`'s
  Dockerfile/.gitignore/requirements/workflow/terraform pattern verbatim,
  renamed to `eu-vat-check-api` (service, tfstate bucket
  `eu-vat-check-tfstate`, Artifact Registry repo).
- `app/vies.py`: stdlib-only (`re`, `json`, `urllib.request`) checker.
  `normalize_vat` (strip spaces/dots/dashes, `GR`→`EL` alias, optional
  `country=` param wins over inline prefix), `FORMATS` regex table for 27
  EU states + `XI`, `check_vat` (calls VIES `GET /ms/{cc}/vat/{number}`,
  maps `userError` → 200/400/503/502), `vies_status` (`GET /check-status`),
  `validate` orchestrator (format check first — invalid format never
  reaches VIES, returns 200 `format_valid:false`).
- `app/main.py`: `/health` open, `/validate` + `/status` behind
  `X-RapidAPI-Proxy-Secret` constant-time check (unset env var = disabled,
  same pattern as bet #1), 503s carry `Retry-After: 30`.
- Tests: `tests/test_vies.py` (37 cases total across both files) —
  normalization, format regex hits/misses, error mapping for every VIES
  `userError` code via monkeypatched `_fetch`. `tests/test_api.py` — live
  hit against `IE6388047V` (Google Ireland, this bet's `example.com`),
  format-invalid → 200, unknown country → 400, `/status` live, proxy-secret
  gate. **37/37 passed locally**, live VIES call succeeded during the test
  run (Google Ireland returned valid).
- `pip-audit` on `requirements.txt` + `requirements-dev.txt`: **0
  vulnerabilities**.
- `terraform fmt -check` clean, `terraform init -backend=false` +
  `terraform validate`: **valid**. `terraform/terraform.tfvars` `project_id`
  still a placeholder — set in Phase 2.

### Checkpoint 1 — done 2026-09-04

Pushed to https://github.com/lele25896/eu-vat-check-api (public, master
branch, first commit `cd23b4a`). CI is red as expected (no WIF secrets
yet).

## Phase 2 — in progress 2026-09-04

- **2.1 ★ done**: `bq ls --project_id=project-8efbf414-9044-47b6-ae0`
  confirmed empty, Gabriele confirmed, billing unlinked from "My First
  Project" — freed a slot on `01848B-AE8053-ECCE44`.
- **2.2 ★ done**: new project `vat-check-api-817540` created (`vat` was
  *not* rejected as a word this time, no fallback needed), billing linked,
  set as active `gcloud config` project.
- **2.3 done**: APIs enabled (run/artifactregistry/monitoring/
  iamcredentials/cloudresourcemanager). GCS bucket
  `gs://eu-vat-check-tfstate` created. Artifact Registry repo
  `eu-vat-check-api` created in `europe-west1` — first attempt hit
  `PERMISSION_DENIED` on `artifactregistry.repositories.create` despite
  confirmed `roles/owner`; retried ~20s later and it succeeded (IAM/API
  propagation lag right after project creation, not a real permissions
  problem — same kind of gotcha as bet #1's missing-services discovery,
  worth remembering if a fresh-project command 403s on the first try).
  `terraform/terraform.tfvars` `project_id` updated to `vat-check-api-817540`.
  Docker Desktop wasn't running — started it, polled until the engine was
  ready (~30s), then built and pushed the image to
  `europe-west1-docker.pkg.dev/vat-check-api-817540/eu-vat-check-api/eu-vat-check-api:latest`
  (digest `sha256:8e5fa5430dae5...`). Several base-image layers mounted
  cross-project from `site-health-api-178823/ssl-site-health-api` (same
  `python:3.11-slim` base, harmless dedup, not a data leak).

### Stopped before `gcloud run deploy` (2.4 ★)

Gabriele said stop here rather than confirm the first public/unauthenticated
deploy this session. Nothing after this point has run: no Cloud Run
service, no `terraform import`, no WIF, no RapidAPI wiring. Resume with the
exact command in the plan's §2.4 / README's Deploy section:

```
gcloud run deploy eu-vat-check-api --image europe-west1-docker.pkg.dev/vat-check-api-817540/eu-vat-check-api/eu-vat-check-api:latest --region europe-west1 --allow-unauthenticated --memory 256Mi --max-instances 2
```

Then smoke test, then §2.5 (`terraform import` of the 5 resources already
created manually), then §2.6 (WIF for CI), then Phase 3 (RapidAPI wiring).
