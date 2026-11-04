locals {
  tags = merge(
    {
      application = "stock-forecasting-platform"
      managed-by  = "terraform"
    },
    var.tags,
  )
  database_url = format(
    "postgresql+psycopg://%s:%s@%s:5432/%s?sslmode=require",
    var.database_user,
    urlencode(random_password.database.result),
    azurerm_postgresql_flexible_server.app.fqdn,
    var.database_name,
  )
}

resource "azurerm_resource_group" "app" {
  name     = "rg-${var.name}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "app" {
  name                = "vnet-${var.name}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  address_space       = ["10.40.0.0/16"]
  tags                = local.tags
}

resource "azurerm_subnet" "container_apps" {
  name                 = "snet-container-apps"
  resource_group_name  = azurerm_resource_group.app.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.40.0.0/23"]

  delegation {
    name = "container-apps"
    service_delegation {
      name = "Microsoft.App/environments"
    }
  }
}

resource "azurerm_subnet" "database" {
  name                 = "snet-postgresql"
  resource_group_name  = azurerm_resource_group.app.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.40.4.0/24"]

  delegation {
    name = "postgresql"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

resource "azurerm_private_dns_zone" "database" {
  name                = "private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.app.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "database" {
  name                  = "${var.name}-postgresql"
  private_dns_zone_name = azurerm_private_dns_zone.database.name
  virtual_network_id    = azurerm_virtual_network.app.id
  resource_group_name   = azurerm_resource_group.app.name
  registration_enabled  = false
  tags                  = local.tags
}

resource "random_password" "database" {
  length           = 32
  special          = true
  override_special = "!#$%&*+-=?@^_"
}

resource "azurerm_postgresql_flexible_server" "app" {
  name                          = "psql-${var.name}"
  resource_group_name           = azurerm_resource_group.app.name
  location                      = azurerm_resource_group.app.location
  version                       = "17"
  delegated_subnet_id           = azurerm_subnet.database.id
  private_dns_zone_id           = azurerm_private_dns_zone.database.id
  public_network_access_enabled = false
  administrator_login           = var.database_user
  administrator_password        = random_password.database.result
  zone                          = var.database_zone
  sku_name                      = var.database_sku_name
  storage_mb                    = 131072
  backup_retention_days         = 14
  geo_redundant_backup_enabled  = true
  tags                          = local.tags

  high_availability {
    mode                      = "ZoneRedundant"
    standby_availability_zone = var.database_standby_zone
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.database]
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.app.id
  charset   = "UTF8"
  collation = "en_US.utf8"

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_account" "data" {
  name                            = substr(replace("st${var.name}data", "-", ""), 0, 24)
  resource_group_name             = azurerm_resource_group.app.name
  location                        = azurerm_resource_group.app.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  min_tls_version                 = "TLS1_2"
  public_network_access_enabled   = false
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  infrastructure_encryption_enabled = true
  tags                            = local.tags

  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 14
    }
    container_delete_retention_policy {
      days = 14
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container" "data" {
  name                  = "platform-data"
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_container_registry" "app" {
  name                          = substr(replace("acr${var.name}", "-", ""), 0, 50)
  resource_group_name           = azurerm_resource_group.app.name
  location                      = azurerm_resource_group.app.location
  sku                           = "Premium"
  admin_enabled                 = false
  public_network_access_enabled = true
  zone_redundancy_enabled       = true
  tags                          = local.tags
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.name}"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "registry_pull" {
  scope                = azurerm_container_registry.app.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_role_assignment" "storage_data" {
  scope                = azurerm_storage_account.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_key_vault" "app" {
  name                          = substr("kv-${var.name}", 0, 24)
  location                      = azurerm_resource_group.app.location
  resource_group_name           = azurerm_resource_group.app.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  enable_rbac_authorization     = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = true
  tags                          = local.tags
}

data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "deployment_key_vault" {
  scope                = azurerm_key_vault.app.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = local.database_url
  key_vault_id = azurerm_key_vault.app.id
  content_type = "SQLAlchemy PostgreSQL connection URL"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.deployment_key_vault]
}

resource "azurerm_key_vault_secret" "jwt_public_key" {
  name         = "jwt-public-key"
  value        = var.jwt_public_key
  key_vault_id = azurerm_key_vault.app.id
  content_type = "PEM public key"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.deployment_key_vault]
}

resource "azurerm_role_assignment" "runtime_key_vault" {
  scope                = azurerm_key_vault.app.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_log_analytics_workspace" "app" {
  name                = "log-${var.name}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_app_environment" "app" {
  name                           = "cae-${var.name}"
  location                       = azurerm_resource_group.app.location
  resource_group_name            = azurerm_resource_group.app.name
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.app.id
  infrastructure_subnet_id       = azurerm_subnet.container_apps.id
  internal_load_balancer_enabled = true
  zone_redundancy_enabled        = true
  tags                           = local.tags
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${var.name}-api"
  container_app_environment_id = azurerm_container_app_environment.app.id
  resource_group_name          = azurerm_resource_group.app.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.app.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.app.id
  }

  secret {
    name                = "jwt-public-key"
    key_vault_secret_id = azurerm_key_vault_secret.jwt_public_key.versionless_id
    identity            = azurerm_user_assigned_identity.app.id
  }

  template {
    min_replicas = var.minimum_replicas
    max_replicas = var.maximum_replicas

    container {
      name    = "api"
      image   = var.app_image
      cpu     = 1
      memory  = "2Gi"
      command = ["stock-predictor"]
      args    = ["serve"]

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
        name        = "SP_DATABASE__URL"
        secret_name = "database-url"
      }
      env {
        name        = "SP_API__JWT_VERIFICATION_KEY"
        secret_name = "jwt-public-key"
      }

      startup_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/health/live"
        interval_seconds        = 5
        timeout                 = 3
        failure_count_threshold = 12
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/health/live"
        interval_seconds        = 15
        timeout                 = 3
        failure_count_threshold = 4
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/health/ready"
        interval_seconds        = 10
        timeout                 = 3
        failure_count_threshold = 3
      }
    }
  }

  ingress {
    external_enabled = false
    target_port      = 8080
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  depends_on = [
    azurerm_role_assignment.registry_pull,
    azurerm_role_assignment.runtime_key_vault,
  ]
}

resource "azurerm_container_app_job" "migration" {
  name                         = "caj-${var.name}-migrate"
  location                     = azurerm_resource_group.app.location
  resource_group_name          = azurerm_resource_group.app.name
  container_app_environment_id = azurerm_container_app_environment.app.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 3
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.app.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.app.id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "migration"
      image   = var.app_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["stock-predictor"]
      args    = ["db-upgrade"]

      env {
        name        = "SP_DATABASE__URL"
        secret_name = "database-url"
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.registry_pull,
    azurerm_role_assignment.runtime_key_vault,
  ]
}
