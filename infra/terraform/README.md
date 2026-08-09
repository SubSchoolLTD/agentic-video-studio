# Terraform bootstrap

This module owns the reproducible Google Cloud topology: APIs, isolated network, runtime identity/IAM, Artifact Registry, private versioned media bucket with lifecycle, Cloud SQL PostgreSQL, Secret Manager placeholders, Pub/Sub with DLQ, Workflows/Scheduler, and optionally the four Cloud Run services.

1. Copy `terraform.tfvars.example` to an ignored `terraform.tfvars` and use an isolated project.
2. Export `TF_VAR_sql_user_password`; do not place a real password in a tfvars file.
3. Run `terraform init`, `terraform plan`, and `terraform apply` with `deploy_runtime_services=false`.
4. Add the first version to every created secret through Secret Manager.
5. Build immutable images and set their references plus stable API/web URLs.
6. Set `deploy_runtime_services=true` and apply again.

Set `github_repository` to enable keyless GitHub Actions deployment. Copy the resulting workload identity provider and deployer service-account email into the repository secrets expected by `.github/workflows/deploy.yml`; do not create or upload a service-account JSON key.

OAuth consent-screen configuration and external provider review remain documented manual operations because those provider workflows are not fully exposed as Terraform resources. Secret values are intentionally not managed in Terraform state.
