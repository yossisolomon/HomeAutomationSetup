# HomeAutomationSetup

A self-hosted home automation stack built on [Home Assistant](https://www.home-assistant.io/) and several free, open-source companion services, all wired together with Docker Compose.

---

## Services

| Service | Description | Default Port |
|---|---|---|
| **Home Assistant** | Core home automation platform | `8123` (host network) |
| **Mosquitto** | Lightweight MQTT broker for IoT device messaging | `1883` (MQTT), `9001` (WebSocket) |
| **Node-RED** | Visual flow editor for automations and integrations | `1880` |
| **ESPHome** | Firmware builder & OTA updater for ESP32/ESP8266 devices | `6052` (host network) |
| **Portainer** | Web-based Docker management UI | `9000` (HTTP), `9443` (HTTPS) |

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) ≥ 24
- [Docker Compose](https://docs.docker.com/compose/install/) ≥ 2 (ships with Docker Desktop)
- A Linux host (Raspberry Pi, mini-PC, or VM) is recommended for full hardware access.

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/yossisolomon/HomeAutomationSetup.git
cd HomeAutomationSetup

# 2. (Optional) Set your timezone in docker-compose.yml for the Node-RED service
#    Look for TZ=America/New_York and replace with your timezone.

# 3. Bring everything up
docker compose up -d

# 4. Open Home Assistant in your browser
#    http://<host-ip>:8123
```

---

## Directory Layout

```
.
├── docker-compose.yml          # All service definitions
├── config/                     # Home Assistant configuration (auto-created on first run)
├── mosquitto/
│   ├── config/
│   │   └── mosquitto.conf      # Mosquitto broker settings
│   ├── data/                   # Persistent MQTT data (auto-created)
│   └── log/                    # Broker logs (auto-created)
├── nodered/
│   └── data/                   # Node-RED flows & settings (auto-created)
├── esphome/
│   └── config/                 # ESPHome device YAML files (auto-created)
└── portainer/
    └── data/                   # Portainer state (auto-created)
```

---

## Connecting Services in Home Assistant

### MQTT (Mosquitto)
Because Home Assistant uses `network_mode: host` it can reach Mosquitto at `localhost:1883`.

In Home Assistant go to **Settings → Devices & Services → Add Integration → MQTT** and use:
- **Broker:** `localhost`
- **Port:** `1883`

### Node-RED
Install the [node-red-contrib-home-assistant-websocket](https://flows.nodered.org/node/node-red-contrib-home-assistant-websocket) palette inside Node-RED, then configure the HA server URL as `http://<host-ip>:8123`.

### ESPHome
Open `http://<host-ip>:6052` to create and flash firmware for DIY ESP devices.  Once flashed, Home Assistant will auto-discover them via mDNS.

---

## Security Notes

- **Mosquitto** is configured with `allow_anonymous true` for ease of initial setup. For production, generate a password file (`mosquitto_passwd`) and set `allow_anonymous false`.
- **Portainer** prompts you to create an admin account on first visit — do this immediately.
- Place all services behind a reverse proxy (e.g., Nginx Proxy Manager) with HTTPS before exposing them to the internet.

---

## Stopping the Stack

```bash
docker compose down
```

To also remove all persistent data volumes (⚠️ destructive):

```bash
docker compose down -v
```
