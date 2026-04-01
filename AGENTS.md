# AGENTS

This file describes the AI agent guidelines and conventions for working with this repository.

---

## Purpose

This repository manages a self-hosted home automation stack.  Any AI agent (Copilot, Codex, etc.) working on this project should follow the conventions below to keep the stack maintainable and secure.

---

## Repository Conventions

### Docker Compose
- All services live in `docker-compose.yml` at the repo root.
- Pin image tags to `stable` or a specific version — never use `latest` in production.  The current `latest` tags are acceptable during initial bootstrapping and should be pinned once the stack is stable.
- Keep each service's persistent data under its own top-level folder (e.g., `mosquitto/`, `nodered/`, `esphome/`).
- Use named bind-mounts (`./service/data:/container/path`) rather than anonymous Docker volumes so that data location is explicit.

### Home Assistant Configuration
- Home Assistant YAML configuration lives under `config/`.
- Do **not** commit secrets (API keys, passwords, tokens). Use Home Assistant's [Secrets](https://www.home-assistant.io/docs/configuration/secrets/) (`secrets.yaml`) and add `config/secrets.yaml` to `.gitignore`.
- Prefer UI-managed integrations over manual YAML where possible.

### Mosquitto MQTT
- The broker config is in `mosquitto/config/mosquitto.conf`.
- `allow_anonymous true` is only for local development.  For any internet-facing deployment, switch to password-based auth and set `allow_anonymous false`.

### Node-RED
- Flow exports (JSON) should be committed to `nodered/flows/` when you want to version-control automations.

### ESPHome
- Device YAML files live in `esphome/config/`.  Commit device configs; do not commit compiled firmware binaries.

### Prometheus & Grafana
- Prometheus configuration lives in `prometheus/config/prometheus.yml`.  Commit this file; do not commit the TSDB data directory (`prometheus/data/`).
- Grafana persistent data (dashboards, data sources) is stored in `grafana/data/` and excluded from version control.
- When adding a new exporter or service to scrape, add a corresponding `scrape_configs` entry in `prometheus.yml`.

---

## Making Changes

1. **Small, focused commits** — one logical change per commit.
2. **Document** any new service in `README.md` (services table + connection instructions).
3. **Validate** `docker-compose.yml` before committing:
   ```bash
   docker compose config
   ```
4. **Security first** — never expose the stack to the internet without HTTPS and proper authentication.

---

## Adding a New Service

1. Add the service block to `docker-compose.yml`.
2. Create a `<service>/` directory for persistent data and any seed config files.
3. Update the **Services** table and connection instructions in `README.md`.
4. Update this file if the new service introduces new conventions.
