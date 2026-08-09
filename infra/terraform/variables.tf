variable "project_id" {
  description = "Google Cloud project for the isolated Agentic Video Studio environment."
  type        = string
}

variable "region" {
  description = "Primary Google Cloud region."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment label."
  type        = string
  default     = "prod"
}

variable "sql_user_password" {
  description = "Cloud SQL application-user password. Supply through TF_VAR_sql_user_password; never commit it."
  type        = string
  sensitive   = true
}

variable "api_image" {
  description = "Immutable API container image reference."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "web_image" {
  description = "Immutable web container image reference."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "clickhouse_image" {
  description = "ClickHouse competition-instance image reference."
  type        = string
  default     = "clickhouse/clickhouse-server:26.5"
}

variable "grafana_image" {
  description = "Grafana image with provisioned datasource and dashboard."
  type        = string
  default     = "grafana/grafana:13.1"
}

variable "app_base_url" {
  description = "Stable public API URL used as the OIDC audience and OAuth callback base."
  type        = string
  default     = "https://example.invalid"
}

variable "web_base_url" {
  description = "Stable public web URL allowed by CORS."
  type        = string
  default     = "https://example.invalid"
}

variable "additional_web_origins" {
  description = "Additional public web origins allowed by CORS, such as a custom domain."
  type        = list(string)
  default     = ["https://studio.subschool.us"]
}

variable "deploy_runtime_services" {
  description = "Create Cloud Run services after images exist and all secret placeholders have versions."
  type        = bool
  default     = false
}

variable "min_api_instances" {
  type    = number
  default = 1
}

variable "labels" {
  type    = map(string)
  default = {}
}

variable "github_repository" {
  description = "Optional owner/repository allowed to deploy through GitHub OIDC, for example SubSchool/agentic-video-studio."
  type        = string
  default     = ""
}
