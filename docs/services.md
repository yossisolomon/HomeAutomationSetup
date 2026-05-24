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
