data "google_project" "current" {}

locals {
  labels = merge({
    application = "agentic-video-studio"
    environment = var.environment
    managed-by  = "terraform"
  }, var.labels)

  required_services = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudscheduler.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "texttospeech.googleapis.com",
    "workflowexecutions.googleapis.com",
    "workflows.googleapis.com",
    "youtube.googleapis.com",
    "youtubeanalytics.googleapis.com",
  ])

  secret_names = toset([
    "api-key-pepper",
    "app-demo-token",
    "clickhouse-password",
    "cloud-sql-password",
    "database-url",
    "google-api-key",
    "grafana-admin-password",
    "parallel-api-key",
    "secret-encryption-key",
    "webhook-signing-secret",
    "youtube-client-id",
    "youtube-client-secret",
    "youtube-refresh-token",
  ])

  runtime_roles = toset([
    "roles/aiplatform.user",
    "roles/artifactregistry.reader",
    "roles/cloudsql.client",
    "roles/logging.logWriter",
    "roles/pubsub.publisher",
    "roles/run.invoker",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/workflows.invoker",
  ])

  api_plain_env = {
    APP_ENV                        = var.environment
    APP_AUTH_MODE                  = "demo"
    APP_BASE_URL                   = var.app_base_url
    WEB_BASE_URL                   = var.web_base_url
    ALLOWED_ORIGINS                = var.web_base_url
    PROVIDER_MODE                  = "live"
    GOOGLE_CLOUD_PROJECT           = var.project_id
    GOOGLE_CLOUD_LOCATION          = var.region
    GOOGLE_CLOUD_STORAGE_BUCKET    = google_storage_bucket.media.name
    GOOGLE_RUNTIME_SERVICE_ACCOUNT = google_service_account.runtime.email
    GOOGLE_PUBSUB_TOPIC            = google_pubsub_topic.domain_events.name
    GEMINI_MODEL                   = "gemini-2.5-flash"
    VEO_MODEL                      = "veo-3.1-generate-001"
    GOOGLE_TTS_VOICE               = "en-US-Chirp3-HD-Achernar"
    GOOGLE_GENAI_USE_VERTEXAI      = "true"
    YOUTUBE_REDIRECT_URI           = "${var.app_base_url}/v1/connections/youtube/callback"
    YOUTUBE_REFRESH_TOKEN_SECRET   = "youtube-refresh-token"
    STORAGE_ROOT                   = "/tmp/avs-media"
    CLICKHOUSE_USER                = "avs"
    GRAFANA_URL                    = var.deploy_runtime_services ? google_cloud_run_v2_service.grafana[0].uri : ""
  }

  api_secret_env = {
    API_KEY_PEPPER         = "api-key-pepper"
    APP_DEMO_TOKEN         = "app-demo-token"
    CLICKHOUSE_PASSWORD    = "clickhouse-password"
    DATABASE_URL           = "database-url"
    GOOGLE_API_KEY         = "google-api-key"
    PARALLEL_API_KEY       = "parallel-api-key"
    SECRET_ENCRYPTION_KEY  = "secret-encryption-key"
    WEBHOOK_SIGNING_SECRET = "webhook-signing-secret"
    YOUTUBE_CLIENT_ID      = "youtube-client-id"
    YOUTUBE_CLIENT_SECRET  = "youtube-client-secret"
  }
}

resource "google_project_service" "required" {
  for_each = local.required_services

  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "main" {
  name                    = "avs-network"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.required]
}

resource "google_compute_subnetwork" "main" {
  name                     = "avs-${var.region}"
  region                   = var.region
  network                  = google_compute_network.main.id
  ip_cidr_range            = "10.42.0.0/24"
  private_ip_google_access = true
}

resource "google_service_account" "runtime" {
  account_id   = "avs-runtime"
  display_name = "Agentic Video Studio runtime"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "deployer" {
  account_id   = "avs-github-deployer"
  display_name = "Agentic Video Studio GitHub deployer"

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "deployer_roles" {
  for_each = toset([
    "roles/cloudbuild.builds.editor",
    "roles/run.admin",
    "roles/serviceusage.serviceUsageConsumer",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_act_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_iam_workload_identity_pool" "github" {
  count = var.github_repository == "" ? 0 : 1

  workload_identity_pool_id = "avs-github"
  display_name              = "Agentic Video Studio GitHub"
  description               = "Keyless GitHub Actions deployments"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count = var.github_repository == "" ? 0 : 1

  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "Agentic Video Studio repository"
  attribute_condition                = "assertion.repository == '${var.github_repository}'"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_deployer" {
  count = var.github_repository == "" ? 0 : 1

  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repository}"
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = local.runtime_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "agentic-video-studio"
  description   = "Agentic Video Studio runtime images"
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "media" {
  name                        = "${var.project_id}-avs-media"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age            = 30
      matches_prefix = ["intermediate/"]
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "build_source" {
  name                        = "${var.project_id}-avs-build-source"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels

  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket_iam_member" "deployer_build_source" {
  bucket = google_storage_bucket.build_source.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_storage_bucket_iam_member" "runtime_media" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_sql_database_instance" "postgres" {
  name                = "avs-postgres"
  region              = var.region
  database_version    = "POSTGRES_15"
  deletion_protection = true

  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
    }

    ip_configuration {
      ipv4_enabled = true
    }

    user_labels = local.labels
  }

  depends_on = [google_project_service.required]
}

resource "google_sql_database" "application" {
  name     = "agentic_video_studio"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "application" {
  name     = "avs_app"
  instance = google_sql_database_instance.postgres.name
  password = var.sql_user_password
}

resource "google_secret_manager_secret" "runtime" {
  for_each = local.secret_names

  secret_id = each.value
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "runtime_access" {
  for_each = google_secret_manager_secret.runtime

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "oauth_version_writer" {
  secret_id = google_secret_manager_secret.runtime["youtube-refresh-token"].id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_pubsub_topic" "domain_events" {
  name   = "avs-domain-events"
  labels = local.labels

  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "dead_letter" {
  name   = "avs-domain-events-dlq"
  labels = local.labels
}

resource "google_pubsub_subscription" "observability" {
  name                       = "avs-domain-events-observability"
  topic                      = google_pubsub_topic.domain_events.id
  message_retention_duration = "604800s"
  ack_deadline_seconds       = 30

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
}

resource "google_pubsub_topic_iam_member" "pubsub_dlq_publisher" {
  topic  = google_pubsub_topic.dead_letter.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "pubsub_subscription_reader" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_workflows_workflow" "metrics_collector" {
  name            = "avs-metrics-collector"
  region          = var.region
  description     = "Run due YouTube 24h and 7d metric checkpoints"
  service_account = google_service_account.runtime.id
  source_contents = file("${path.module}/../workflows/metrics-collector.yaml")
  labels          = local.labels

  depends_on = [google_project_service.required]
}

resource "google_cloud_scheduler_job" "metrics_collector" {
  name        = "avs-metrics-collector"
  region      = var.region
  description = "Start the durable metric checkpoint workflow every 15 minutes"
  schedule    = "*/15 * * * *"
  time_zone   = "UTC"

  http_target {
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.metrics_collector.id}/executions"
    http_method = "POST"
    headers     = { "Content-Type" = "application/json" }
    body = base64encode(jsonencode({
      argument = jsonencode({ api_url = var.app_base_url })
    }))

    oauth_token {
      service_account_email = google_service_account.runtime.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "300s"
  }

  depends_on = [google_project_iam_member.runtime_roles]
}

resource "google_cloud_run_v2_service" "clickhouse" {
  count = var.deploy_runtime_services ? 1 : 0

  name                = "agentic-video-studio-clickhouse"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.labels

  template {
    service_account = google_service_account.runtime.email
    timeout         = "300s"

    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    containers {
      image = var.clickhouse_image

      ports {
        container_port = 8080
      }

      resources {
        limits   = { cpu = "2", memory = "4Gi" }
        cpu_idle = false
      }

      env {
        name  = "CLICKHOUSE_DB"
        value = "default"
      }
      env {
        name  = "CLICKHOUSE_USER"
        value = "avs"
      }
      env {
        name  = "CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT"
        value = "1"
      }
      env {
        name = "CLICKHOUSE_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime["clickhouse-password"].secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime_access]
}

resource "google_cloud_run_v2_service" "grafana" {
  count = var.deploy_runtime_services ? 1 : 0

  name                = "agentic-video-studio-grafana"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.labels

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    containers {
      image = var.grafana_image

      ports {
        container_port = 8080
      }

      resources {
        limits   = { cpu = "1", memory = "1Gi" }
        cpu_idle = false
      }

      env {
        name  = "CLICKHOUSE_HOST"
        value = trimprefix(google_cloud_run_v2_service.clickhouse[0].uri, "https://")
      }
      env {
        name  = "CLICKHOUSE_USER"
        value = "avs"
      }
      env {
        name  = "GF_SECURITY_ADMIN_USER"
        value = "admin"
      }
      env {
        name  = "GF_AUTH_ANONYMOUS_ENABLED"
        value = "false"
      }
      env {
        name = "CLICKHOUSE_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime["clickhouse-password"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GF_SECURITY_ADMIN_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime["grafana-admin-password"].secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime_access]
}

resource "google_cloud_run_v2_service" "api" {
  count = var.deploy_runtime_services ? 1 : 0

  name                = "agentic-video-studio-api"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.labels

  template {
    service_account = google_service_account.runtime.email
    timeout         = "3600s"

    scaling {
      min_instance_count = var.min_api_instances
      max_instance_count = 2
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8080
      }

      resources {
        limits   = { cpu = "2", memory = "4Gi" }
        cpu_idle = false
      }

      dynamic "env" {
        for_each = local.api_plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "CLICKHOUSE_URL"
        value = google_cloud_run_v2_service.clickhouse[0].uri
      }

      dynamic "env" {
        for_each = local.api_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.runtime[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.runtime_access,
    google_sql_database.application,
  ]
}

resource "google_cloud_run_v2_service" "web" {
  count = var.deploy_runtime_services ? 1 : 0

  name                = "agentic-video-studio-web"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.labels

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = var.web_image

      ports {
        container_port = 8080
      }

      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }

      env {
        name  = "NUXT_PUBLIC_API_BASE"
        value = var.app_base_url
      }
      env {
        name  = "NUXT_PUBLIC_GRAFANA_URL"
        value = google_cloud_run_v2_service.grafana[0].uri
      }
      env {
        name = "NUXT_PUBLIC_DEMO_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime["app-demo-token"].secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime_access]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = var.deploy_runtime_services ? {
    api        = google_cloud_run_v2_service.api[0].name
    web        = google_cloud_run_v2_service.web[0].name
    clickhouse = google_cloud_run_v2_service.clickhouse[0].name
    grafana    = google_cloud_run_v2_service.grafana[0].name
  } : {}

  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = "allUsers"
}
