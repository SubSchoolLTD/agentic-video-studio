# Configuration and secrets

Copy `.env.example` to `.env`. Never commit `.env`, OAuth tokens, provider responses containing credentials, or generated client-secret JSON files.

## Modes

- Local and CI: `PROVIDER_MODE=mock`.
- Integration: `PROVIDER_MODE=hybrid`, with Parallel and Google variables set.
- Demo/live: `PROVIDER_MODE=live`, Google Cloud project, Vertex AI APIs, Parallel key, and optional YouTube OAuth credentials configured.

## Secret mapping

| Local env | Google Secret Manager / GitHub secret |
|---|---|
| `PARALLEL_API_KEY` | `PARALLEL_API_KEY` |
| `GOOGLE_API_KEY` | `GOOGLE_API_KEY` |
| `JWT_SECRET` | `jwt-secret` |
| `SECRET_ENCRYPTION_KEY` | `secret-encryption-key` (optional dedicated application-data key; `JWT_SECRET` is the fallback) |
| `SENDPULSE_ID` | `sendpulse-id` |
| `SENDPULSE_SECRET` | `sendpulse-secret` |
| `PAYPAL_CLIENT_ID` | `paypal-client-id` |
| `PAYPAL_SECRET` | `paypal-secret` |
| `PAYPAL_WEBHOOK_ID` | `paypal-webhook-id` (optional; capture return remains authoritative) |
| `CLOUD_SQL_PASSWORD` | `CLOUD_SQL_PASSWORD` |
| `YOUTUBE_CLIENT_ID` | `YOUTUBE_CLIENT_ID` |
| `YOUTUBE_CLIENT_SECRET` | `YOUTUBE_CLIENT_SECRET` |
| `YOUTUBE_REFRESH_TOKEN` | `YOUTUBE_REFRESH_TOKEN` (local override only; deployed OAuth versions this in Secret Manager) |
| `CLICKHOUSE_PASSWORD` | `CLICKHOUSE_PASSWORD` |
| `GRAFANA_ADMIN_PASSWORD` | `GRAFANA_ADMIN_PASSWORD` |
| `GRAFANA_OTLP_HEADERS` | `GRAFANA_OTLP_HEADERS` |
| `WEBHOOK_SIGNING_SECRET` | `WEBHOOK_SIGNING_SECRET` |
| `API_KEY_PEPPER` | `API_KEY_PEPPER` |

Production must set `APP_AUTH_MODE=jwt`, `EMAIL_DELIVERY_MODE=sendpulse`, `PAYPAL_ENV=live`, PayPal server credentials, and a strong `JWT_SECRET`. PayPal credentials never reach the browser; Orders v2 create/capture and amount verification happen on the API. Demo authentication is accepted only in explicit local/test environments. The deployed API mounts the Streamable HTTP MCP resource at `/mcp`; every request must carry a user JWT or revocable project-scoped API key as `Authorization: Bearer …`. The optional standalone MCP process may use `APP_API_TOKEN`, but there is no shared or anonymous production credential. In the combined Cloud Run service set `MCP_API_BASE=http://127.0.0.1:8080`, so authenticated MCP domain calls use container loopback instead of consuming a second public Cloud Run request.

Google runtime identity should use workload identity/service account credentials in deployment; do not place long-lived service-account JSON in GitHub when federation is available.

Instagram and TikTok do not require developer apps. A user signs in through the Connections screen; their password and optional one-time code are used only by a transient Playwright process and are never persisted. The resulting browser storage state (cookies/local storage) is encrypted with AES-256-GCM before it is written to the tenant-isolated connection record in the application database. The encryption key is derived from `SECRET_ENCRYPTION_KEY` when configured, otherwise from the production `JWT_SECRET`; ciphertext is never returned by the API. Disconnecting clears it from the connection record.

The production deploy sets `APP_BASE_URL`, `WEB_BASE_URL`, and the YouTube callback. The API image includes a pinned Playwright Chromium runtime. Provider CAPTCHAs are not bypassed: the connection is marked for reauthentication and the user must retry the normal sign-in flow.

`GOOGLE_RUNTIME_SERVICE_ACCOUNT` pins the identity accepted by internal OIDC endpoints. `GOOGLE_PUBSUB_TOPIC` is the non-secret domain event topic name. Both should be empty in local and CI environments unless integration tests explicitly target Google Cloud.

`CLICKHOUSE_URL` and `GRAFANA_URL` are non-secret service endpoints. `CLICKHOUSE_PASSWORD` and `GRAFANA_ADMIN_PASSWORD` are secrets. The API uses ClickHouse's dedicated `X-ClickHouse-User` and `X-ClickHouse-Key` headers so the credential is compatible with Cloud Run's authorization proxy without exposing it in a query string.

The configured model defaults include `gemini-2.5-flash` for research, `gemini-2.5-pro` for editorial planning/review, `gemini-2.5-flash-image`, and `veo-3.1-generate-001`. See `config.py` and the deployment's environment for the actual selected models. The deprecated Veo preview endpoint is intentionally not used.

## Database migrations

Run `alembic upgrade head` before starting a deployed API revision. Local startup also calls `create_all` as a developer-friendly fallback, but migrations are the production source of truth.
