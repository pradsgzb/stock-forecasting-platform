locals {
  required_services = toset([
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
  ])
  labels = {
    application = "stock-forecasting-platform"
    managed-by  = "terraform"
  }
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "app" {
  name                    = "${var.name}-network"
  auto_create_subnetworks = false

  depends_on = [google_project_service.required]
}

resource "google_compute_subnetwork" "app" {
  name                     = "${var.name}-${var.region}"
  region                   = var.region
  network                  = google_compute_network.app.id
  ip_cidr_range            = var.network_cidr
  private_ip_google_access = true
}

resource "google_compute_global_address" "private_services" {
  name          = "${var.name}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.app.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.app.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]

  depends_on = [google_project_service.required]
}

resource "random_password" "database" {
  length           = 32
  special          = true
  override_special = "!#$%&*+-=?@^_"
}

resource "google_sql_database_instance" "app" {
  name             = "${var.name}-postgres"
  region           = var.region
  database_version = "POSTGRES_17"

  settings {
    tier              = var.database_tier
    availability_type = var.database_high_availability ? "REGIONAL" : "ZONAL"
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00"
      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }

    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
      record_client_address   = false
    }

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.app.id
      enable_private_path_for_google_cloud_services = true
    }

    user_labels = local.labels
  }

  deletion_protection = var.deletion_protection

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_sql_database" "app" {
  name     = var.database_name
  instance = google_sql_database_instance.app.name
}

resource "google_sql_user" "app" {
  name     = var.database_user
  instance = google_sql_database_instance.app.name
  password = random_password.database.result
}

resource "google_storage_bucket" "data" {
  name                        = "${var.project_id}-${var.name}-data"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = 604800
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "ARCHIVE"
    }
  }
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = var.name
  description   = "Stock forecasting platform OCI artifacts"
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.required]
}

resource "google_service_account" "app" {
  account_id   = var.name
  display_name = "Stock forecasting platform runtime"
}

resource "google_project_iam_member" "cloud_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_storage_bucket_iam_member" "data_access" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "${var.name}-database-url"
  replication {
    auto {}
  }
  labels = local.labels
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  secret_data = format(
    "postgresql+psycopg://%s:%s@%s:5432/%s",
    var.database_user,
    urlencode(random_password.database.result),
    google_sql_database_instance.app.private_ip_address,
    var.database_name,
  )
}

resource "google_secret_manager_secret" "jwt_public_key" {
  secret_id = "${var.name}-jwt-public-key"
  replication {
    auto {}
  }
  labels = local.labels
}

resource "google_secret_manager_secret_version" "jwt_public_key" {
  secret      = google_secret_manager_secret.jwt_public_key.id
  secret_data = var.jwt_public_key
}

resource "google_secret_manager_secret_iam_member" "database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "jwt_public_key" {
  secret_id = google_secret_manager_secret.jwt_public_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_cloud_run_v2_service" "api" {
  name     = "${var.name}-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  labels   = local.labels

  template {
    service_account = google_service_account.app.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.minimum_instances
      max_instance_count = var.maximum_instances
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.app.name
        subnetwork = google_compute_subnetwork.app.name
      }
    }

    containers {
      image = var.app_image
      args  = ["serve"]

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "SP_APP__ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "SP_API__HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "SP_API__PORT"
        value = "8080"
      }
      env {
        name  = "SP_API__DOCS_ENABLED"
        value = "false"
      }
      env {
        name  = "SP_API__ALLOWED_HOSTS"
        value = var.api_allowed_hosts
      }
      env {
        name  = "SP_API__JWT_ISSUER"
        value = "https://identity.example.invalid/"
      }
      env {
        name  = "SP_API__JWT_AUDIENCE"
        value = "stock-forecasting-platform"
      }
      env {
        name = "SP_DATABASE__URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SP_API__JWT_VERIFICATION_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_public_key.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        failure_threshold     = 12
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 3
        http_get {
          path = "/health/live"
          port = 8080
        }
      }

      liveness_probe {
        failure_threshold = 4
        period_seconds    = 15
        timeout_seconds   = 3
        http_get {
          path = "/health/live"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.database_url,
    google_secret_manager_secret_iam_member.jwt_public_key,
  ]
}

resource "google_cloud_run_v2_job" "migration" {
  name     = "${var.name}-migrate"
  location = var.region
  labels   = local.labels

  template {
    template {
      service_account = google_service_account.app.email
      timeout         = "900s"
      max_retries     = 3

      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = google_compute_network.app.name
          subnetwork = google_compute_subnetwork.app.name
        }
      }

      containers {
        image = var.app_image
        args  = ["db-upgrade"]
        env {
          name = "SP_DATABASE__URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
}
