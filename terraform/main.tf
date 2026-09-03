terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # backend GCS dal giorno 1 — bucket va creato una tantum a mano prima di
  # `terraform init` (chicken-and-egg: non puoi usare Terraform per creare
  # il backend di Terraform stesso). Sostituisci il nome bucket.
  backend "gcs" {
    bucket = "eu-vat-check-tfstate"
    prefix = "cloud-run"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "run" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

# required for WIF token exchange (google-github-actions/auth in CI)
resource "google_project_service" "iam_credentials" {
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
}

# required by google_project_service itself to manage other services
resource "google_project_service" "resource_manager" {
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "api" {
  repository_id = var.service_name
  format        = "DOCKER"
  location      = var.region
  depends_on    = [google_project_service.artifact_registry]
}

resource "google_cloud_run_v2_service" "api" {
  name     = var.service_name
  location = var.region

  template {
    # cost cap: public endpoint on a small budget
    # ponytail: provider v6 reports manual/min_instance_count drift (0 vs
    # null) on every plan regardless of this config — cosmetic, doesn't
    # touch the deployed image/revision (ignore_changes covers that below).
    # Upgrade path: revisit if a future provider version stops normalizing it.
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.service_name}/${var.service_name}:latest"
      resources {
        limits = { memory = "256Mi" }
      }
      liveness_probe {
        http_get { path = "/health" }
      }
    }
  }

  # Terraform possiede l'infra statica; GitHub Actions possiede le revision
  # (nuove immagini a ogni deploy) — senza questo, `apply` farebbe rollback
  # a `:latest` sovrascrivendo l'ultimo deploy della CI.
  lifecycle {
    ignore_changes = [template, client, client_version]
  }

  depends_on = [google_project_service.run]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_project_service" "monitoring" {
  service            = "monitoring.googleapis.com"
  disable_on_destroy = false
}

resource "google_monitoring_uptime_check_config" "health" {
  display_name = "${var.service_name}-health"
  timeout      = "10s"
  period       = "300s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(google_cloud_run_v2_service.api.uri, "https://")
    }
  }

  depends_on = [google_project_service.monitoring]
}
