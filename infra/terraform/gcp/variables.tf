variable "project_id" {
  description = "Existing GCP project ID used for the deployment."
  type        = string
}

variable "region" {
  description = "GCP region for regional services."
  type        = string
  default     = "us-central1"
}

variable "name" {
  description = "DNS-safe resource-name prefix."
  type        = string
  default     = "stock-predictor"
}

variable "app_image" {
  description = "Immutable OCI image reference, preferably pinned by sha256 digest."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.app_image))
    error_message = "app_image must be pinned by an OCI sha256 digest."
  }
}

variable "jwt_public_key" {
  description = "PEM public key used to verify API access tokens."
  type        = string
  sensitive   = true
}

variable "api_allowed_hosts" {
  description = "JSON array of permitted API host names."
  type        = string
  default     = "[\"stock-predictor.internal\"]"
}

variable "network_cidr" {
  description = "CIDR for the application subnet."
  type        = string
  default     = "10.42.0.0/24"
}

variable "database_name" {
  description = "Application database name."
  type        = string
  default     = "stock_platform"
}

variable "database_user" {
  description = "Application database login."
  type        = string
  default     = "stock_app"
}

variable "database_tier" {
  description = "Cloud SQL machine tier."
  type        = string
  default     = "db-custom-2-7680"
}

variable "database_high_availability" {
  description = "Enable regional high availability for Cloud SQL."
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Protect stateful resources from accidental deletion."
  type        = bool
  default     = true
}

variable "minimum_instances" {
  description = "Minimum Cloud Run API instances."
  type        = number
  default     = 1
}

variable "maximum_instances" {
  description = "Maximum Cloud Run API instances."
  type        = number
  default     = 10
}
