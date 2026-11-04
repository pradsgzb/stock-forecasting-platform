variable "subscription_id" {
  description = "Azure subscription receiving the reference deployment."
  type        = string
}

variable "location" {
  description = "Azure region for regional application resources."
  type        = string
  default     = "eastus2"
}

variable "name" {
  description = "Lowercase resource-name prefix."
  type        = string
  default     = "stockforecast"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{4,19}$", var.name))
    error_message = "name must be 5-20 lowercase alphanumeric characters, beginning with a letter."
  }
}

variable "app_image" {
  description = "Immutable OCI image reference. Production must use an sha256 digest."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.app_image))
    error_message = "app_image must be pinned by an OCI sha256 digest."
  }
}

variable "jwt_public_key" {
  description = "PEM public key used to verify internal API access tokens."
  type        = string
  sensitive   = true
}

variable "api_allowed_hosts" {
  description = "JSON array consumed by SP_API__ALLOWED_HOSTS."
  type        = string
  default     = "[\"stock-forecasting.internal\"]"
}

variable "database_sku_name" {
  description = "Azure Database for PostgreSQL Flexible Server SKU."
  type        = string
  default     = "GP_Standard_D2ds_v5"
}

variable "database_zone" {
  description = "Primary PostgreSQL availability zone."
  type        = string
  default     = "1"
}

variable "database_standby_zone" {
  description = "Standby availability zone for zone-redundant PostgreSQL."
  type        = string
  default     = "2"
}

variable "database_name" {
  description = "Application database name."
  type        = string
  default     = "stock_platform"
}

variable "database_user" {
  description = "Application database administrator login."
  type        = string
  default     = "stock_app"
}

variable "minimum_replicas" {
  description = "Minimum API replicas."
  type        = number
  default     = 2
}

variable "maximum_replicas" {
  description = "Maximum API replicas."
  type        = number
  default     = 10
}


variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}
