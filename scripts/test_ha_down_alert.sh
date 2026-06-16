#!/usr/bin/env bash
# =============================================================================
# Manual verification for the "Home Assistant Down" Grafana alert (backlog #18).
#
# Stops Home Assistant, waits for the blacky_ha_down rule to reach FIRING, gives
# Grafana time to dispatch the Telegram notification, then ALWAYS restores HA
# (even on Ctrl-C / SSH drop — see the EXIT trap) and reports whether the send
# attempt errored. Grafana does not log a clear "delivered" line, so the final
# confirmation is you receiving the Telegram message.
#
# Run ON blacky (needs docker + the grafana .env):
#   bash ~/homeassistant/scripts/test_ha_down_alert.sh
# Detached + connection-proof (recommended over SSH):
#   setsid bash ~/homeassistant/scripts/test_ha_down_alert.sh > /tmp/ha_down_test.log 2>&1 < /dev/null &
#   tail -f /tmp/ha_down_test.log
# =============================================================================
set -u

HA_DIR="${HA_DIR:-$HOME/homeassistant}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
PROM_URL="${PROM_URL:-http://localhost:9090}"
MAX_WAIT="${MAX_WAIT:-300}"        # seconds to wait for FIRING before giving up
DISPATCH_GRACE="${DISPATCH_GRACE:-45}"  # seconds after FIRING for group_wait + send

# Grafana admin creds come from the repo .env (same file docker-compose uses).
set -a; . "${HA_DIR}/.env"; set +a
GU="${GRAFANA_ADMIN_USER}"; GP="${GRAFANA_ADMIN_PASSWORD}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

rule_state() {
  # Lowercased state of the "Home Assistant Down" rule (normal|pending|firing|"").
  curl -s -u "${GU}:${GP}" "${GRAFANA_URL}/api/prometheus/grafana/api/v1/rules" \
    | python3 -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception: print(''); sys.exit()
for g in d.get('data',{}).get('groups',[]):
    for r in g['rules']:
        if 'Assistant' in r.get('name',''): print((r.get('state') or '').lower())
"
}

up_val() {
  curl -s "${PROM_URL}/api/v1/query?query=up%7Bjob%3D%22homeassistant%22%7D" \
    | python3 -c "import sys,json; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else 'NODATA')"
}

restore() {
  log "RESTORE: docker start homeassistant"
  docker start homeassistant >/dev/null 2>&1 || true
}
trap restore EXIT

START_TS=$(date -u +%Y-%m-%dT%H:%M:%S)
log "STOP homeassistant (HA-down alert test; will auto-restore)"
docker stop homeassistant >/dev/null 2>&1

fired=0
elapsed=0
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
  sleep 10; elapsed=$((elapsed + 10))
  st=$(rule_state)
  log "t+${elapsed}s up=$(up_val) rule=${st:-none}"
  if [ "$st" = "firing" ]; then
    fired=1
    log "ALERT FIRING — waiting ${DISPATCH_GRACE}s for group_wait + Telegram dispatch"
    sleep "$DISPATCH_GRACE"
    break
  fi
done

if [ "$fired" = "1" ]; then
  log "RESULT: rule FIRED. Checking Grafana for send failures in this window…"
  if docker logs grafana --since "$START_TS" 2>&1 \
       | grep -qiE 'Notify for alerts failed.*telegram'; then
    log "  ⚠️  Grafana logged a Telegram send FAILURE (see: docker logs grafana | grep -i 'Notify for alerts')."
    log "      Transient sends retry after group_interval; confirm whether the message arrived."
  else
    log "  ✅ No Telegram send failure logged — confirm you received the Telegram message."
  fi
else
  log "RESULT: rule did NOT reach FIRING within ${MAX_WAIT}s — investigate ha_up / the rule."
fi

restore; trap - EXIT
sleep 10
log "recovery: HA health=$(docker inspect homeassistant --format '{{.State.Health.Status}}' 2>/dev/null) up=$(up_val)"
log "DONE"
