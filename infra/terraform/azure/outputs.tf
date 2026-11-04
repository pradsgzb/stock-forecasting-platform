output "resource_group_name" {
  description = "Resource group containing the deployment."
  value       = azurerm_resource_group.app.name
}

output "container_registry" {
  description = "OCI registry login server."
  value       = azurerm_container_registry.app.login_server
}

output "api_fqdn" {
  description = "Internal Container Apps API FQDN."
  value       = azurerm_container_app.api.ingress[0].fqdn
}

output "migration_job_name" {
  description = "Manual migration job to execute before traffic promotion."
  value       = azurerm_container_app_job.migration.name
}

output "data_storage_account" {
  description = "Private storage account for data-plane adapters."
  value       = azurerm_storage_account.data.name
}

output "database_fqdn" {
  description = "Private PostgreSQL endpoint."
  value       = azurerm_postgresql_flexible_server.app.fqdn
  sensitive   = true
}
