output "artifact_repository" {
  value = google_artifact_registry_repository.images.name
}

output "media_bucket" {
  value = google_storage_bucket.media.name
}

output "cloud_sql_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "github_deployer_service_account" {
  value = google_service_account.deployer.email
}

output "github_workload_identity_provider" {
  value = var.github_repository == "" ? null : google_iam_workload_identity_pool_provider.github[0].name
}

output "pubsub_topic" {
  value = google_pubsub_topic.domain_events.id
}

output "metrics_workflow" {
  value = google_workflows_workflow.metrics_collector.id
}

output "service_urls" {
  value = var.deploy_runtime_services ? {
    api        = google_cloud_run_v2_service.api[0].uri
    web        = google_cloud_run_v2_service.web[0].uri
    clickhouse = google_cloud_run_v2_service.clickhouse[0].uri
    grafana    = google_cloud_run_v2_service.grafana[0].uri
  } : {}
}
