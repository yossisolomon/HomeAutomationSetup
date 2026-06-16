# Per-Service Conventions

## Mosquitto (MQTT)

- Config: `mosquitto/config/mosquitto.conf`
- `allow_anonymous true` is for local dev only. Switch to password auth for any internet-facing deployment.

## Node-RED

- Version-controlled flows go in `nodered/flows/` as JSON exports.

## ESPHome

- Device YAML configs live in `esphome/config/`. Commit device configs; never commit compiled firmware binaries.

## Prometheus

- Config: `prometheus/config/prometheus.yml` — commit this.
- Data dir `prometheus/data/` — excluded from version control (TSDB).
- When adding a new exporter or service, add a `scrape_configs` entry in `prometheus.yml`.

## Grafana

- Persistent data (dashboards, data sources): `grafana/data/` — excluded from version control.
- Export dashboards as JSON and commit to `grafana/dashboards/` if you want them in git.

### Alerting

- Alert rules: `grafana/provisioning/alerting/rules.yml`. Contact point + notification
  policy: `grafana/provisioning/alerting/contact_points.yml.tmpl` (the entrypoint
  substitutes `${TELEGRAM_BOT_TOKEN}` / `${TELEGRAM_CHAT_ID}` from `.env` into a
  rendered `contact_points.yml`). All alerts route to the `blacky-notify` Telegram
  contact point. `ha_up` / the `blacky_ha_down` rule come from the HA `/api/prometheus`
  scrape — see `prometheus/config/prometheus.yml`.
- **Re-provisioning gotcha:** the entrypoint renders provisioning into the container's
  `/tmp` (the mounted dir is `:ro`). It `rm -rf`s that dir first, so a plain
  `docker restart grafana` now picks up edited rules/contact points. (Before that fix
  a restart silently kept stale files — you needed `docker compose up -d --force-recreate grafana`.)
- **Stray DB integrations:** `grafana/data/` persists the alerting DB, which can retain
  contact-point integrations that are no longer in provisioning (e.g. a legacy email
  receiver under `blacky-notify` that logs `SMTP not configured`). File provisioning
  does not delete extras. Remove an unmanaged integration by its UID:
  `curl -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" -X DELETE \
   http://localhost:3000/api/v1/provisioning/contact-points/<uid>`.
- Verify the HA-down alert end-to-end with `scripts/test_ha_down_alert.sh` (stops HA,
  waits for FIRING, auto-restores; you confirm the Telegram message arrives).
