#!/bin/sh
# Configure Grafana Telegram contact point via API.
# When run in the grafana-setup container, env vars come from docker-compose env_file.
# When run manually from the host, sources .env from the repo root.
set -eu

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    # shellcheck disable=SC1091
    set -a && . "${SCRIPT_DIR}/../.env" && set +a
fi

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_ADMIN_USER}"
GRAFANA_PASS="${GRAFANA_ADMIN_PASSWORD}"
BOT_TOKEN="${TELEGRAM_BOT_TOKEN}"
CHAT_ID="${TELEGRAM_CHAT_ID}"

echo "Waiting for Grafana to be ready..."
until curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASS}" "${GRAFANA_URL}/api/health" > /dev/null 2>&1; do
    sleep 3
done
echo "Grafana is up"

curl -sf -X DELETE "${GRAFANA_URL}/api/v1/provisioning/contact-points/telegram" \
  -u "${GRAFANA_USER}:${GRAFANA_PASS}" 2>/dev/null || true

echo "Creating Telegram contact point..."
curl -sf -X POST "${GRAFANA_URL}/api/v1/provisioning/contact-points" \
  -H "Content-Type: application/json" \
  -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
  -d "{
    \"uid\": \"telegram\",
    \"name\": \"blacky-notify\",
    \"type\": \"telegram\",
    \"settings\": {
      \"bottoken\": \"${BOT_TOKEN}\",
      \"chatid\": \"${CHAT_ID}\",
      \"message\": \"{{ range .Alerts }}\n🚨 {{ .Labels.severity | toUpper }}: {{ .Annotations.summary }}\n{{ end }}\"
    }
  }"
echo ""
echo "Grafana alerting configured"
