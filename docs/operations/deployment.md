# Google Cloud deployment

The live hackathon environment uses four Cloud Run services:

- Web: `agentic-video-studio-web` in `us-central1`.
- API/workflow: `agentic-video-studio-api` in `us-central1` with always-allocated CPU and one minimum instance for long-running provider operations.
- Analytics event store: `agentic-video-studio-clickhouse`, authenticated with ClickHouse headers backed by Secret Manager.
- Operations UI: `agentic-video-studio-grafana`, with a provisioned ClickHouse datasource and Pipeline, AI, Media, Publishing and Cost dashboards.

Durable state lives in the `avs-postgres` Cloud SQL PostgreSQL instance. Media and manifests live in the private `subschool-484119-avs-media` bucket. Images are built by Cloud Build into the `agentic-video-studio` Artifact Registry repository. The runtime service account is `avs-runtime` and receives provider, database, object, logging, Pub/Sub, and secret access without a service-account JSON key.

The reproducible topology lives in `infra/terraform`. Its two-phase `deploy_runtime_services` switch creates foundational resources and secret placeholders first, then Cloud Run only after immutable images and secret versions exist. Terraform never stores provider secret values; the only manual console work is OAuth consent/provider review.

## Images

```bash
gcloud builds submit . \
  --config=infra/cloudbuild-api.yaml \
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/PROJECT_ID/agentic-video-studio/api:COMMIT_SHA

gcloud builds submit . \
  --config=infra/cloudbuild-web.yaml \
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/PROJECT_ID/agentic-video-studio/web:COMMIT_SHA

gcloud builds submit . \
  --config=infra/cloudbuild-clickhouse.yaml \
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/PROJECT_ID/agentic-video-studio/clickhouse:26.5

gcloud builds submit . \
  --config=infra/cloudbuild-grafana.yaml \
  --substitutions=_IMAGE=us-central1-docker.pkg.dev/PROJECT_ID/agentic-video-studio/grafana:13.1
```

The API image applies Alembic migrations before starting. Production secrets are mounted from Secret Manager. The YouTube OAuth callback adds refresh-token versions to a dedicated secret; it never writes the token to PostgreSQL or the repository. ClickHouse DDL is versioned under `infra/clickhouse/initdb.d`; Grafana datasources and dashboards are immutable provisioned files.

## Metrics and observability

Publication confirmation creates independent `24h` and `7d` checkpoints in PostgreSQL. `POST /v1/metric-checkpoints/{id}/collect` is idempotent, invokes the official YouTube Data and Analytics APIs, preserves unsupported or delayed values as unavailable rather than zero, writes a normalized snapshot to PostgreSQL and ClickHouse, and creates a low-confidence Performance Review plus a proposed Strategy Version. Provider errors never turn into invented metrics.

The public ClickHouse endpoint still requires `X-ClickHouse-User` and `X-ClickHouse-Key`; the password is injected from Secret Manager. Grafana requires its provisioned admin login. The competition deployment intentionally uses one warm Cloud Run ClickHouse instance for a real, inexpensive demo event stream. Its local disk is ephemeral; production should use ClickHouse Cloud or persistent compute without changing the append-only schema or API sink.

`avs-metrics-collector` is a Google Workflow started every 15 minutes by Cloud Scheduler. Its OIDC-authenticated automation pass polls due RSS, launches scheduled research/backlog replenishment, refreshes provider processing states, retries due webhook deliveries and evaluates operational alerts; its metrics pass collects due checkpoints. No application bearer secret is copied into Scheduler. Domain events are published to `avs-domain-events`, with a retained observability subscription available for verification and independent consumers.

## Smoke checks

```bash
curl -fsS https://agentic-video-studio-api-912667618167.us-central1.run.app/v1/health
curl -fsS https://agentic-video-studio-grafana-912667618167.us-central1.run.app/api/health
E2E_BASE_URL=https://agentic-video-studio-web-912667618167.us-central1.run.app \
  pnpm --filter @avs/web exec playwright test tests/e2e/navigation.spec.ts
```

The full create → render → approve → prepare/commit → metric checkpoint e2e remains provider-mocked in CI to prevent accidental spend. Live Parallel, Gemini, Veo, TTS, Cloud Storage, YouTube connector, ClickHouse, and Grafana checks are run separately against the deployed environment.
