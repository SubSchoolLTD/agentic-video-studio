# OVH production deployment

Framewise runs as an isolated Docker Compose project under `/home/ubuntu/apps/Framewise` on the shared OVH host. PostgreSQL, ClickHouse, the API, web application, Grafana and the optional scheduler all use `framewise_*` container, network and volume names. The only shared resource is the existing `caddy_net` network and the `subschool_caddy_prod` reverse proxy.

Deployments run from `.github/workflows/deploy.yml` on pushes to `main` or by manual dispatch. The workflow renders `.env.production` from GitHub Actions secrets, synchronizes the repository and runs `ops/deploy-production.sh`. The generated environment file is not committed.

The scale-to-zero Google token broker has a separate `.github/workflows/deploy-google-token-broker.yml` workflow. It runs only when the broker source or image definition changes, or when manually dispatched, so ordinary OVH deployments do not incur Cloud Build work or create unnecessary Artifact Registry versions.

## Cutover gates

Two production environment variables make the first deployment safe while DNS still targets Google:

- `ACTIVATE_CADDY=false` copies and validates only `/config/sites/framewise.caddy`. It does not reload the shared Caddy process or request a certificate. Set it to `true` only after `studio.subschool.us` resolves to `137.74.202.47`.
- `LOCAL_SCHEDULER_ENABLED=false` leaves the local 15-minute scheduler stopped while Google Cloud Scheduler and Workflows remain active. Set it to `true` after the final PostgreSQL copy and disable the Google scheduler before doing so.

The Caddy deployment always backs up only the Framewise drop-in, validates the entire imported Caddy configuration and restores the prior drop-in on failure. It never edits `/home/ubuntu/apps/SubSchool/ops/Caddyfile` or restarts neighboring projects.

## Durable data

- PostgreSQL: `framewise_postgres_data`
- ClickHouse: `framewise_clickhouse_data`
- generated media and locally stored OAuth documents: `framewise_app_data`
- database backups: `/home/ubuntu/apps/Framewise/backups`, retained for 14 days by the deployment script

`MEDIA_STORAGE_BACKEND=local` makes new media writes local. The former GCS bucket name remains configured only as a namespace so existing `gs://` database references resolve to the same relative path after the objects have been copied into `/data/media`.

Static secrets are managed as GitHub Actions secrets. OAuth documents created at runtime are dynamic application state, not deployment configuration, and live under the persistent application volume with mode `0600`.

## Google services retained

Gemini, Veo and Text-to-Speech continue to run in Google Cloud. Organization policy forbids exporting service-account keys, so a scale-to-zero Cloud Run token broker supplies short-lived OAuth access tokens to OVH after validating `GOOGLE_TOKEN_BROKER_SECRET`. Its dedicated service account has only Vertex AI and Service Usage roles; the long-lived broker secret lives in both Google Secret Manager and GitHub Actions, while the actual Google access tokens expire within an hour. Cloud SQL, GCS, Pub/Sub, Workflows and Cloud Scheduler can be removed only after DNS cutover, final data verification and local scheduler activation. The small request-only broker, Artifact Registry image and its required Google APIs remain.

## Rollback

Before DNS cleanup, rollback is changing `studio.subschool.us` back to its Google target and leaving `ACTIVATE_CADDY=false`. The old Google services and data must remain intact until the OVH smoke checks, authentication, media playback, provider calls and scheduler have all been verified.
