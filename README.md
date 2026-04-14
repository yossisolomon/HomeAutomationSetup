# HomeAutomationSetup

ThinkPad T400 smart-home server — headless Debian 13, running a Docker Compose stack.

## Services

| Service | Port | Description |
|---|---|---|
| Home Assistant | 8123 | Automation hub |
| Mosquitto | 1883, 9001 | MQTT broker |
| Node-RED | 1880 | Flow-based automation |
| ESPHome | 6052 | ESP device management |
| Portainer | 9000, 9443 | Docker management UI |
| Prometheus | 9090 | Metrics collection |
| Grafana | 3000 | Dashboards & alerts |
| node-exporter | 9100 | Host metrics |
| cAdvisor | 8080 | Container metrics |

## Bootstrap

### Prerequisites

- Fresh Debian 13 (Trixie) installation — netinstall with SSH server + standard utilities
- Ethernet connection (recommended)
- SSD partitioned as described below (setup.sh verifies this on first run)

### First run

```bash
# From another machine, SSH in and run:
sudo apt-get install -y git
git clone git@github.com:yossisolomon/HomeAutomationSetup.git ~/homeassistant
sudo ~/homeassistant/setup.sh
```

After setup completes:

```bash
sudo reboot   # fully loads tp-smapi for battery thresholds
```

Then start the stack:

```bash
cd ~/homeassistant && docker compose up -d
```

### Subsequent runs

`setup.sh` is idempotent — safe to re-run after adding hardware or reinstalling.

## SSD Partition Layout

```
/boot           ~1GB    ext4   noatime,nodev,nosuid   label: boot
/               ~28GB   ext4   noatime                label: root
/var/lib/docker ~56GB   ext4   noatime,nodev,nosuid   label: docker
/home           ~146GB  ext4   noatime,nodev,nosuid   label: home
swap            ~2GB    swap                           label: swap
```

`/var/lib/docker` **must** be on its own dedicated partition — setup.sh will fail if it isn't.

## Backup HDD

Connect via USB before running setup.sh. It will be auto-detected, labelled `ha-backup`, and mounted at `/mnt/backup`.

Add `/mnt/backup:/backup` to the `homeassistant` service volumes in `docker-compose.yml`, then configure HA's native backup to write there: **Settings → System → Backups**.

## Alerts (Grafana)

Pre-provisioned alert rules (CPU >85%, RAM >90%, Disk >85%, Battery low/critical) fire via the `blacky-notify` contact point.

To enable email:
1. Generate a Gmail App Password: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Create `~/homeassistant/.env`:
   ```
   GF_SMTP_ENABLED=true
   GF_SMTP_PASSWORD=<your-16-char-app-password>
   ```
3. `docker compose restart grafana`

## Monitoring `blacky.local`

After the first successful `docker compose up -d`:

```bash
# Docker
docker ps
docker compose logs -f

# UFW
sudo ufw status verbose

# Battery
sudo tlp-stat -b | grep -i thresh
cat /sys/class/power_supply/BAT0/capacity

# Grafana → http://blacky.local:3000  (admin / admin on first login)
# Home Assistant → http://blacky.local:8123
```

## SSH access

From any machine on the local network:

```bash
ssh yossi@blacky.local
```

The server advertises via mDNS (`avahi-daemon`) — no static IP needed.
