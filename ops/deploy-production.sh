#!/usr/bin/env bash
set -euo pipefail

app_root="${FRAMEWISE_ROOT:-/home/ubuntu/apps/Framewise}"
compose_file="${app_root}/docker-compose.production.yml"
env_file="${app_root}/.env.production"
caddy_container="${FRAMEWISE_CADDY_CONTAINER:-subschool_caddy_prod}"
caddy_dropin="/config/sites/framewise.caddy"
activate_caddy="${ACTIVATE_CADDY:-false}"
local_scheduler_enabled="${LOCAL_SCHEDULER_ENABLED:-false}"

if [[ ! -f "${env_file}" ]]; then
  echo "Missing ${env_file}" >&2
  exit 1
fi
chmod 600 "${env_file}"

required_keys=(POSTGRES_PASSWORD JWT_SECRET PARALLEL_API_KEY PAYPAL_CLIENT_ID PAYPAL_SECRET SENDPULSE_ID SENDPULSE_SECRET CLICKHOUSE_PASSWORD GRAFANA_ADMIN_PASSWORD INTERNAL_AUTOMATION_TOKEN GOOGLE_TOKEN_BROKER_URL GOOGLE_TOKEN_BROKER_SECRET)
for key in "${required_keys[@]}"; do
  if ! grep -Eq "^${key}=.+" "${env_file}"; then
    echo "Missing required production setting: ${key}" >&2
    exit 1
  fi
done

compose() {
  sudo docker compose --project-name framewise --env-file "${env_file}" -f "${compose_file}" "$@"
}

cd "${app_root}"
compose config --quiet

mkdir -p "${app_root}/backups"
if sudo docker inspect framewise_postgres >/dev/null 2>&1; then
  backup_path="${app_root}/backups/framewise-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
  if sudo docker exec framewise_postgres pg_isready -U framewise -d framewise >/dev/null 2>&1; then
    sudo docker exec framewise_postgres pg_dump -U framewise -d framewise | gzip -9 > "${backup_path}"
    find "${app_root}/backups" -type f -name 'framewise-*.sql.gz' -mtime +14 -delete
  fi
fi

profile_args=()
if [[ "${local_scheduler_enabled}" == "true" ]]; then
  profile_args+=(--profile scheduler)
fi
compose "${profile_args[@]}" up -d --build --remove-orphans

for service in postgres clickhouse api web grafana; do
  container="framewise_${service}"
  for attempt in {1..60}; do
    status="$(sudo docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container}" 2>/dev/null || true)"
    if [[ "${status}" == "healthy" ]]; then
      break
    fi
    if (( attempt % 6 == 0 )); then
      echo "Waiting for ${container}: ${status:-not-created} (${attempt}/60)"
    fi
    if [[ "${attempt}" == "60" ]]; then
      compose logs --tail=200 "${service}"
      echo "${container} did not become healthy" >&2
      exit 1
    fi
    sleep 5
  done
done

sudo docker exec "${caddy_container}" mkdir -p /config/sites
had_previous=0
if sudo docker exec "${caddy_container}" test -f "${caddy_dropin}"; then
  had_previous=1
  sudo docker exec "${caddy_container}" cp "${caddy_dropin}" "${caddy_dropin}.backup"
fi
sudo docker cp "${app_root}/infra/ovh/framewise.caddy" "${caddy_container}:${caddy_dropin}"

if ! sudo docker exec "${caddy_container}" caddy validate --config /etc/caddy/Caddyfile; then
  if [[ "${had_previous}" == "1" ]]; then
    sudo docker exec "${caddy_container}" mv "${caddy_dropin}.backup" "${caddy_dropin}"
  else
    sudo docker exec "${caddy_container}" rm -f "${caddy_dropin}"
  fi
  echo "Caddy validation failed; the prior shared routing state was restored" >&2
  exit 1
fi
sudo docker exec "${caddy_container}" rm -f "${caddy_dropin}.backup"

if [[ "${activate_caddy}" == "true" ]]; then
  sudo docker exec "${caddy_container}" caddy reload --config /etc/caddy/Caddyfile
  for attempt in {1..30}; do
    if curl --fail --silent --show-error --max-time 10 https://studio.subschool.us/v1/health >/dev/null; then
      exit 0
    fi
    sleep 5
  done
  echo "Public Framewise health check failed" >&2
  exit 1
fi

echo "Framewise is healthy internally. Caddy configuration is validated but intentionally not reloaded before DNS cutover."
