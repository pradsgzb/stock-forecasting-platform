output "api_service_name" {
  description = "Cloud Run API service name."
  value       = google_cloud_run_v2_service.api.name
}

output "api_service_uri" {
  description = "Internal Cloud Run API URI."
  value       = google_cloud_run_v2_service.api.uri
}

output "migration_job_name" {
  description = "Cloud Run migration job invoked by the delivery pipeline."
  value       = google_cloud_run_v2_job.migration.name
}

output "artifact_repository" {
  description = "Artifact Registry repository ID."
  value       = google_artifact_registry_repository.app.id
}

output "data_bucket" {
  description = "Private versioned data bucket."
  value       = google_storage_bucket.data.name
}

output "runtime_service_account" {
  description = "Managed runtime service-account email."
  value       = google_service_account.app.email
}
