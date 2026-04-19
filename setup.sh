#!/usr/bin/env bash
# =============================================================================
# ThinkPad T400 — Debian 13 (Trixie) Smart Home Server Bootstrap
# =============================================================================
# Prerequisites:
#   - Fresh Debian 13 Trixie netinstall (SSH server + standard system utilities)
#   - Network connectivity (Ethernet recommended)
#   - SSD installed with the partition layout described in README.md
#   - Run as root from the cloned repo directory:
#       git clone git@github.com:yossisolomon/HomeAutomationSetup.git ~/homeassistant
#       sudo ~/homeassistant/setup.sh
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
MAIN_USER="yossi"
HA_DIR="/home/${MAIN_USER}/homeassistant"
BACKUP_HDD_LABEL="blacky-NAS"
BACKUP_MOUNT="/mnt/nas"

# Battery thresholds (ThinkPad acts as UPS)
BAT_START_THRESH=70
BAT_STOP_THRESH=80

# ── Color helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]]              && error "Run as root:  sudo ${HA_DIR}/setup.sh"
[[ ! -f /etc/debian_version ]] && error "This doesn't look like Debian."
id "$MAIN_USER" &>/dev/null    || error "User '$MAIN_USER' not found. Edit MAIN_USER at the top of this script."

echo ""
echo "=============================================="
echo "  ThinkPad T400 Smart Home Server Setup"
echo "  Debian 13 (Trixie) — Headless Docker Host"
echo "=============================================="
echo ""

# ── 0. Verify SSD partition layout ────────────────────────────────────────────
info "Verifying SSD partition layout..."

PARTITION_WARN=false

check_mount_opts() {
    local MOUNT_POINT="$1"
    shift
    local ACTUAL_OPTS
    ACTUAL_OPTS=$(awk -v mp="$MOUNT_POINT" '$2==mp{print $4}' /proc/mounts | head -1)
    if [[ -z "$ACTUAL_OPTS" ]]; then
        warn "Mount point $MOUNT_POINT not found in /proc/mounts"
        PARTITION_WARN=true
        return
    fi
    for opt in "$@"; do
        if ! echo "$ACTUAL_OPTS" | tr ',' '\n' | grep -qx "$opt"; then
            warn "$MOUNT_POINT missing mount option '$opt' (current: $ACTUAL_OPTS)"
            PARTITION_WARN=true
        fi
    done
}

# /var/lib/docker MUST be on its own dedicated partition (fatal if not)
ROOT_DEV=$(findmnt -n -o SOURCE /)
DOCKER_DEV=$(findmnt -n -o SOURCE /var/lib/docker 2>/dev/null || true)
if [[ -z "$DOCKER_DEV" ]]; then
    error "/var/lib/docker is not on a dedicated partition. Docker images/logs must be isolated from the root FS to prevent disk exhaustion. See README.md for the required partition layout."
fi
[[ "$ROOT_DEV" == "$DOCKER_DEV" ]] && \
    error "/var/lib/docker shares a partition with / ($ROOT_DEV). They must be separate."
info "/var/lib/docker is isolated on $DOCKER_DEV (root is on $ROOT_DEV)"

check_mount_opts /boot           noatime nodev nosuid
check_mount_opts /var/lib/docker noatime nodev nosuid
check_mount_opts /home           noatime nodev nosuid

if [[ "$PARTITION_WARN" == "true" ]]; then
    warn "Some partition options diverge from the recommended layout — non-fatal, check fstab."
else
    info "All partition mount options verified."
fi

# Fix missing partition labels
# Use e2label to read the current label (lsblk caches stale values after writes)
fix_ext4_label() {
    local MOUNTPOINT="$1" LABEL="$2" PART CURRENT
    PART=$(lsblk -o NAME,MOUNTPOINT -l | awk -v mp="$MOUNTPOINT" '$2==mp{print $1}')
    [[ -z "$PART" ]] && return
    CURRENT=$(e2label "/dev/$PART" 2>/dev/null || true)
    if [[ "$CURRENT" != "$LABEL" ]]; then
        info "Setting label '$LABEL' on /dev/$PART (was: '${CURRENT:-empty}')..."
        e2label "/dev/$PART" "$LABEL" || warn "Could not set label on /dev/$PART — non-fatal"
    fi
}
fix_ext4_label /home           home
fix_ext4_label /var/lib/docker docker

SWAP_PART=""
while IFS= read -r P; do
    if blkid "/dev/$P" 2>/dev/null | grep -q 'TYPE="swap"'; then
        SWAP_PART="$P"
        break
    fi
done < <(lsblk -o NAME,TYPE -l | awk '$2=="part"{print $1}')
if [[ -n "$SWAP_PART" ]]; then
    SWAP_LABEL=$(blkid -s LABEL -o value "/dev/$SWAP_PART" 2>/dev/null || true)
    if [[ "$SWAP_LABEL" != "swap" ]]; then
        info "Setting label 'swap' on /dev/$SWAP_PART..."
        swaplabel -L swap "/dev/$SWAP_PART" || warn "Could not set swap label — non-fatal"
    fi
fi

# ── 0.5. Hostname + lid-close behavior ────────────────────────────────────────
info "Setting hostname to 'blacky'..."
hostnamectl set-hostname blacky
if grep -q "^127\.0\.1\.1" /etc/hosts; then
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\tblacky/" /etc/hosts
else
    echo "127.0.1.1	blacky" >> /etc/hosts
fi

info "Disabling sleep/hibernate on lid close (server stays up with lid closed)..."
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/no-lid-sleep.conf <<'LIDEOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
LIDEOF
systemctl restart systemd-logind

# ── 1. System update + base packages ──────────────────────────────────────────
info "Updating system packages..."
apt update && apt upgrade -y

info "Installing base utilities..."
apt install -y \
    curl wget git sudo nano htop tmux lsof \
    ufw fail2ban avahi-daemon avahi-utils \
    build-essential dkms linux-headers-$(uname -r) \
    udisks2 usbutils \
    mosquitto-clients \
    ca-certificates gnupg

systemctl enable avahi-daemon
systemctl start avahi-daemon
info "mDNS active — reachable as blacky.local"

# ── 1b. Swap tuning ───────────────────────────────────────────────────────────
info "Setting swappiness to 10 (prefer RAM, swap only under pressure)..."
if grep -q "vm.swappiness" /etc/sysctl.conf; then
    sed -i "s/vm.swappiness=.*/vm.swappiness=10/" /etc/sysctl.conf
else
    echo "vm.swappiness=10" >> /etc/sysctl.conf
fi
sysctl -w vm.swappiness=10

# ── 2. Add trixie-backports ────────────────────────────────────────────────────
info "Adding trixie-backports repository..."
if ! grep -rq "trixie-backports" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
    echo "deb http://deb.debian.org/debian trixie-backports main" \
        > /etc/apt/sources.list.d/backports.list
    apt update
fi

# ── 3. ThinkPad battery management (tlp + tp-smapi) ──────────────────────────
info "Installing TLP + tp-smapi from backports..."
apt install -y tlp tlp-rdw
apt install -y -t trixie-backports tp-smapi-dkms

modprobe tp_smapi 2>/dev/null || warn "tp_smapi module failed to load (may need reboot)"
grep -q "tp_smapi" /etc/modules || echo "tp_smapi" >> /etc/modules

info "Configuring battery thresholds (${BAT_START_THRESH}%–${BAT_STOP_THRESH}%)..."
sed -i "s/^#\?START_CHARGE_THRESH_BAT0=.*/START_CHARGE_THRESH_BAT0=${BAT_START_THRESH}/" /etc/tlp.conf
sed -i "s/^#\?STOP_CHARGE_THRESH_BAT0=.*/STOP_CHARGE_THRESH_BAT0=${BAT_STOP_THRESH}/" /etc/tlp.conf

grep -q "START_CHARGE_THRESH_BAT0=${BAT_START_THRESH}" /etc/tlp.conf \
    || warn "Battery start threshold may not have applied — check /etc/tlp.conf"
grep -q "STOP_CHARGE_THRESH_BAT0=${BAT_STOP_THRESH}" /etc/tlp.conf \
    || warn "Battery stop threshold may not have applied — check /etc/tlp.conf"

systemctl enable tlp
tlp start || warn "TLP start returned non-zero (may need reboot for tp-smapi)"

# Suppress ACPI evaluation errors on the T400 console.
# thinkpad_acpi always probes ACPI battery methods (BCTG, HEKY, etc.) even on
# models that predate them — they don't exist on the T400 so the kernel logs
# "evaluate failed" at KERN_WARNING (level 4) on every boot.
# tp-smapi handles battery control via SMAPI port I/O instead, so these
# warnings are safe to suppress. loglevel=3 keeps EMERG/ALERT/CRIT on the
# console and silences WARNING and below (errors still go to the journal).
info "Suppressing spurious ACPI console noise (loglevel=3 in GRUB)..."
if ! grep -q "loglevel=3" /etc/default/grub; then
    sed -i 's/^\(GRUB_CMDLINE_LINUX_DEFAULT="[^"]*\)"/\1 loglevel=3"/' /etc/default/grub
    update-grub 2>/dev/null || warn "update-grub failed — check /etc/default/grub manually"
    info "GRUB updated. Console log level takes effect on next reboot."
fi

# ── 3b. Battery → Prometheus textfile + MQTT heartbeat ───────────────────────
# The HA battery *sensor* reads /sys directly via the mounted volume (see §8 note).
# This script handles two separate concerns:
#   1. Prometheus textfile metrics → node_exporter exposes them → Grafana alerts fire
#   2. MQTT heartbeat topic → if this message arrives in HA, MQTT broker is confirmed live
#      (useful as a broker health check independent of Zigbee/other device traffic)
info "Installing battery metrics publisher (Prometheus textfile + MQTT heartbeat)..."

TEXTFILE_DIR="/var/lib/node_exporter/textfile_collector"
mkdir -p "$TEXTFILE_DIR"
chmod 755 "$TEXTFILE_DIR"

cat > /usr/local/bin/ha-battery-metrics.sh <<'BATEOF'
#!/usr/bin/env bash
# ThinkPad battery metrics publisher. Runs every 60 s via systemd timer.
# Requires: mosquitto-clients (for MQTT heartbeat)

CAPACITY=$(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null || echo "")
STATUS=$(  cat /sys/class/power_supply/BAT0/status   2>/dev/null || echo "unknown")
MINUTES_REMAINING=$(cat /sys/devices/platform/smapi/BAT0/remaining_running_time 2>/dev/null || echo "")
CHARGING=$([ "$STATUS" = "Charging" ] && echo 1 || echo 0)

TEXTFILE_DIR="/var/lib/node_exporter/textfile_collector"

# ── 1. Prometheus textfile (picked up by node_exporter → Grafana alerts) ─────
if [[ -n "$CAPACITY" ]]; then
    {
        echo "# HELP thinkpad_battery_capacity_percent ThinkPad T400 battery capacity (%)"
        echo "# TYPE thinkpad_battery_capacity_percent gauge"
        echo "thinkpad_battery_capacity_percent ${CAPACITY}"
        echo "# HELP thinkpad_battery_charging ThinkPad T400 battery charging state (1=charging)"
        echo "# TYPE thinkpad_battery_charging gauge"
        echo "thinkpad_battery_charging ${CHARGING}"
        if [[ "$MINUTES_REMAINING" =~ ^[0-9]+$ ]]; then
            echo "# HELP thinkpad_battery_runtime_minutes Estimated runtime remaining (minutes)"
            echo "# TYPE thinkpad_battery_runtime_minutes gauge"
            echo "thinkpad_battery_runtime_minutes ${MINUTES_REMAINING}"
        fi
    } > "${TEXTFILE_DIR}/battery.prom"
fi

# ── 2. MQTT heartbeat (broker liveness check — HA monitors this topic) ────────
# If Mosquitto auth is enabled, add: -u <user> -P <pass>
mosquitto_pub -h localhost -p 1883 \
    -t "blacky/battery/heartbeat" \
    -m "{\"capacity\": ${CAPACITY:-null}, \"status\": \"${STATUS}\", \"ts\": $(date +%s)}" \
    2>/dev/null || true
# Note: HA does NOT use this topic for the battery sensor.
# Configure an MQTT sensor in HA if you want the heartbeat visible there:
#   mqtt:
#     sensor:
#       - name: "MQTT Heartbeat"
#         state_topic: "blacky/battery/heartbeat"
#         value_template: "{{ value_json.status }}"
BATEOF
chmod +x /usr/local/bin/ha-battery-metrics.sh

cat > /etc/systemd/system/ha-battery-metrics.service <<'SVCEOF'
[Unit]
Description=Publish ThinkPad battery metrics (Prometheus textfile + MQTT heartbeat)
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ha-battery-metrics.sh
SVCEOF

cat > /etc/systemd/system/ha-battery-metrics.timer <<'TIMEREOF'
[Unit]
Description=Run ThinkPad battery metrics publisher every 60 seconds

[Timer]
OnBootSec=30sec
OnUnitActiveSec=60sec
AccuracySec=5sec

[Install]
WantedBy=timers.target
TIMEREOF

systemctl daemon-reload
systemctl enable ha-battery-metrics.timer
systemctl start  ha-battery-metrics.timer
info "Battery metrics publisher active (textfile at ${TEXTFILE_DIR}, MQTT heartbeat to blacky/battery/heartbeat)"

# ── 3c. Battery-aware graceful shutdown ──────────────────────────────────────
# On AC loss: 1-hour timer fires shutdown-if-on-battery.sh (brief outages cancel cleanly).
# Emergency floor: watchdog shuts down at ≤20% regardless (keeps battery in safe 80-20 range).
# Boot grace period: watchdog skips first 10 min after boot to avoid boot/shutdown loops.
info "Installing battery-aware power management..."

cat > /usr/local/bin/on-battery.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
logger -t on-battery "AC lost — starting 1-hour shutdown timer"
systemctl stop battery-shutdown-timer.timer 2>/dev/null || true
systemd-run --unit=battery-shutdown-timer --on-active=3600 \
    /usr/local/bin/shutdown-if-on-battery.sh
logger -t on-battery "Timer started"
SCRIPT
chmod +x /usr/local/bin/on-battery.sh

cat > /usr/local/bin/on-ac.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
systemctl stop battery-shutdown-timer.timer 2>/dev/null \
    && logger -t on-ac "AC restored — timer cancelled" \
    || logger -t on-ac "AC restored (no timer active)"
SCRIPT
chmod +x /usr/local/bin/on-ac.sh

cat > /usr/local/bin/shutdown-if-on-battery.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
STATUS=$(cat /sys/class/power_supply/BAT0/status 2>/dev/null || echo Unknown)
[[ "$STATUS" != "Discharging" ]] && { logger -t battery-shutdown "AC present — no shutdown"; exit 0; }
CAPACITY=$(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null || echo 100)
logger -t battery-shutdown "1h on battery (${CAPACITY}%) — shutting down"
docker stop $(docker ps -q) 2>/dev/null || true
sync; systemctl poweroff
SCRIPT
chmod +x /usr/local/bin/shutdown-if-on-battery.sh

cat > /usr/local/bin/battery-watchdog.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
EMERGENCY_THRESHOLD=20
BOOT_GRACE_SECONDS=600
while true; do
    sleep 120
    UPTIME=$(awk '{print int($1)}' /proc/uptime)
    [[ "$UPTIME" -lt "$BOOT_GRACE_SECONDS" ]] && continue
    STATUS=$(cat /sys/class/power_supply/BAT0/status 2>/dev/null || echo Unknown)
    [[ "$STATUS" == "Discharging" ]] || continue
    CAPACITY=$(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null || echo 100)
    if [[ "$CAPACITY" -le "$EMERGENCY_THRESHOLD" ]]; then
        logger -t battery-watchdog "EMERGENCY: ${CAPACITY}% — shutting down"
        docker stop $(docker ps -q) 2>/dev/null || true
        sync; systemctl poweroff; exit 0
    fi
done
SCRIPT
chmod +x /usr/local/bin/battery-watchdog.sh

cat > /etc/systemd/system/battery-watchdog.service << 'UNIT'
[Unit]
Description=Battery emergency watchdog (shuts down at <=20%)
After=docker.service
Wants=docker.service
[Service]
Type=simple
ExecStart=/usr/local/bin/battery-watchdog.sh
Restart=always
RestartSec=60
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable battery-watchdog
systemctl start battery-watchdog

cat > /etc/udev/rules.d/99-power.rules << 'RULES'
SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ATTR{online}=="0", \
    RUN+="/bin/systemd-run --no-block /usr/local/bin/on-battery.sh"
SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ATTR{online}=="1", \
    RUN+="/bin/systemd-run --no-block /usr/local/bin/on-ac.sh"
RULES
udevadm control --reload-rules
info "Battery-aware power management installed (1h timer + 20% emergency floor)"

# ── 4. Docker Engine (native, no snap, no Colima) ─────────────────────────────
info "Installing Docker Engine..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

usermod -aG docker "$MAIN_USER"
systemctl enable docker
systemctl start docker
info "Docker $(docker --version | awk '{print $3}') installed."

# ── 4b. Docker daemon config (log limits) ─────────────────────────────────────
info "Configuring Docker daemon (log rotation)..."
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'DOCKERJSON'
{
  "data-root": "/var/lib/docker",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
DOCKERJSON
systemctl restart docker

# ── 4c. Weekly Docker cleanup cron ────────────────────────────────────────────
info "Setting up weekly Docker prune cron..."
cat > /etc/cron.weekly/docker-prune <<'PRUNEEOF'
#!/bin/sh
docker system prune -f >> /var/log/docker-prune.log 2>&1
PRUNEEOF
chmod +x /etc/cron.weekly/docker-prune

# ── 4d. Docker data volume permissions ────────────────────────────────────────
# Pre-create bind-mount directories with the correct container UIDs so that
# containers can write to them on first start. Docker would otherwise create
# them as root:root 755, causing permission errors for non-root container users.
#
# Only the top-level directory ownership is set here — files inside were created
# by the containers themselves and retain their original ownership.
info "Preparing Docker data volume directories..."

prepare_vol() {
    local DIR="$1" OWNER="$2" PERMS="${3:-755}"
    mkdir -p "$DIR"
    # Only set ownership on the directory itself, not recursively
    chown "$OWNER" "$DIR"
    chmod "$PERMS" "$DIR"
}

# Mosquitto: UID 1883 (mosquitto user in the eclipse-mosquitto image)
prepare_vol "${HA_DIR}/mosquitto/data" "1883:1883"
prepare_vol "${HA_DIR}/mosquitto/log"  "1883:1883"

# Node-RED: UID 1000
prepare_vol "${HA_DIR}/nodered/data" "1000:1000" "777"

# Prometheus: UID 65534 (nobody)
prepare_vol "${HA_DIR}/prometheus/data" "65534:65534" "777"

# Grafana: UID 472 (grafana user in the official image)
prepare_vol "${HA_DIR}/grafana/data" "472:472" "777"

# Root-owned services (HA, ESPHome, Portainer) — just ensure dirs exist
mkdir -p "${HA_DIR}/config"
mkdir -p "${HA_DIR}/esphome/config"
mkdir -p "${HA_DIR}/portainer/data"

info "Volume directories prepared."

# ── 5. SSH hardening ──────────────────────────────────────────────────────────
info "Hardening SSH..."
SSHD_CONF="/etc/ssh/sshd_config"
if ! grep -q "Smart Home Server Hardening" "$SSHD_CONF"; then
    cat >> "$SSHD_CONF" <<'SSHEOF'

# === Smart Home Server Hardening ===
# Uncomment the next two lines AFTER confirming SSH key login works:
# PermitRootLogin no
# PasswordAuthentication no
SSHEOF
fi
systemctl restart sshd

# ── 6. Firewall (UFW) ─────────────────────────────────────────────────────────
# Two classes of ports behave differently with UFW:
#
# Bridge-networked containers (mosquitto, nodered, grafana, prometheus, etc.):
#   Docker injects iptables DNAT rules into its own DOCKER chain, bypassing
#   UFW's INPUT chain. These ports are open on the LAN regardless of UFW rules.
#
# Host-networked containers (homeassistant, esphome):
#   These bind directly to the host network stack — UFW INPUT rules DO apply
#   and must explicitly allow them, otherwise connections are refused.
#
# Your router handles external firewall duties for the LAN.
info "Configuring UFW..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh                                        # Port 22
ufw allow 5353/udp                                   # mDNS — blacky.local
ufw allow 8123/tcp comment "Home Assistant (host network)"
ufw allow 6052/tcp comment "ESPHome (host network)"
ufw --force enable
info "UFW active. HA (8123) and ESPHome (6052) explicitly allowed; bridge container ports open via Docker."

# ── 6b. Wake-on-LAN persistence ──────────────────────────────────────────────
# NIC resets WoL register on reboot; re-apply via oneshot systemd service.
# To activate: set "Wake on LAN: AC and Battery" in BIOS (Config → Network).
info "Enabling Wake-on-LAN persistence..."
cat > /etc/systemd/system/wol-enable.service << 'UNIT'
[Unit]
Description=Enable Wake-on-LAN on enp0s25
After=network.target
[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -s enp0s25 wol g
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable wol-enable
systemctl start wol-enable || true
info "WoL enabled — set 'Wake on LAN: AC and Battery' in BIOS to activate after power-off"

# ── 7. Mount backup HDD ───────────────────────────────────────────────────────
info "Looking for backup HDD (unmounted ext4, non-SSD disk)..."

BACKUP_DEV=""
while read -r NAME TYPE FSTYPE MOUNTPOINT; do
    [[ "$TYPE"   != "part" ]] && continue
    [[ "$FSTYPE" != "ext4" ]] && continue
    [[ -n "$MOUNTPOINT"    ]] && continue
    [[ "$NAME"   == sda*   ]] && continue   # skip system SSD
    BACKUP_DEV="/dev/$NAME"
    break
done < <(lsblk -o NAME,TYPE,FSTYPE,MOUNTPOINT -l)

if [[ -n "$BACKUP_DEV" ]]; then
    info "Found backup HDD candidate: $BACKUP_DEV"

    CURRENT_LABEL=$(lsblk -o NAME,LABEL -l | awk -v p="${BACKUP_DEV##*/}" '$1==p{print $2}')
    if [[ -z "$CURRENT_LABEL" ]]; then
        info "Labelling $BACKUP_DEV as '${BACKUP_HDD_LABEL}'..."
        e2label "$BACKUP_DEV" "$BACKUP_HDD_LABEL"
    fi

    mkdir -p "$BACKUP_MOUNT"

    if ! grep -q "LABEL=${BACKUP_HDD_LABEL}" /etc/fstab; then
        echo "LABEL=${BACKUP_HDD_LABEL} ${BACKUP_MOUNT} ext4 defaults,nofail,noatime 0 2" >> /etc/fstab
        info "Added fstab entry for backup HDD."
    fi

    mount -a || warn "mount -a returned non-zero — check: journalctl -xe"

    if mountpoint -q "$BACKUP_MOUNT"; then
        info "Backup HDD mounted at ${BACKUP_MOUNT}"
    else
        warn "Backup HDD not mounted at ${BACKUP_MOUNT}."
    fi
else
    warn "No unmounted ext4 partition found for backup HDD."
    warn "Plug in the USB HDD, then run:"
    warn "  e2label /dev/sdX1 ${BACKUP_HDD_LABEL}"
    warn "  echo 'LABEL=${BACKUP_HDD_LABEL} ${BACKUP_MOUNT} ext4 defaults,nofail,noatime 0 2' | tee -a /etc/fstab"
    warn "  mount -a"
fi

# ── 8. GitHub SSH key check ───────────────────────────────────────────────────
MAIN_USER_HOME="/home/${MAIN_USER}"
SSH_KEY="${MAIN_USER_HOME}/.ssh/github_id"

if [[ -f "$SSH_KEY" ]]; then
    chmod 600 "$SSH_KEY"
    info "GitHub SSH key found at ${SSH_KEY}"
else
    warn "No GitHub SSH key found at ${SSH_KEY}"
    warn "Options:"
    warn "  1. Copy from backup HDD: cp ${BACKUP_MOUNT}/path/to/id_ed25519 ${SSH_KEY}"
    warn "  2. Generate new key:     ssh-keygen -t ed25519 -f ${SSH_KEY}"
    warn "  3. Add to GitHub:        cat ${SSH_KEY}.pub"
fi

# ── 9. Docker Compose — pull images ───────────────────────────────────────────
if [[ -f "${HA_DIR}/docker-compose.yml" ]]; then
    info "Pulling Docker images (this may take a while on the T400)..."
    sudo -u "$MAIN_USER" docker compose -f "${HA_DIR}/docker-compose.yml" pull \
        || warn "Docker pull failed — run manually: cd ${HA_DIR} && docker compose pull"
    info "Images pulled. Start with:  cd ${HA_DIR} && docker compose up -d"
else
    warn "No docker-compose.yml found at ${HA_DIR}."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Setup complete!"
echo "=============================================="
echo ""
info "Installed: Docker, TLP, tp-smapi, UFW, fail2ban, avahi-daemon, mosquitto-clients"
info "Hostname:  blacky  (reachable as blacky.local on the local network)"
info "Battery:   Charge thresholds ${BAT_START_THRESH}%–${BAT_STOP_THRESH}%; published to MQTT + Prometheus every 60 s"
info "Lid close: no sleep/hibernate — server stays up"
info "Firewall:  UFW active for SSH (22) + mDNS (5353); container ports open on LAN"
info "Backup HDD: ${BACKUP_MOUNT}"
echo ""
warn "NEXT STEPS:"
warn "  1. Reboot to fully load tp-smapi:  sudo reboot"
warn "  2. After reboot verify battery:    sudo tlp-stat -b"
warn "  3. Start the stack:  cd ${HA_DIR} && docker compose up -d"
warn "  4. Open HA:          http://blacky.local:8123"
warn "  5. Battery sensor: auto-discovered in HA once Mosquitto is running."
warn "     Grafana alerts for CPU/RAM/Disk/Battery are pre-provisioned."
warn "  6. Add to docker-compose homeassistant volumes:  ${BACKUP_MOUNT}/ha:/backup"
warn "     Then Settings → System → Backups writes directly to the HDD."
warn "  7. Once SSH key login is confirmed, harden SSH:"
warn "     Uncomment PermitRootLogin / PasswordAuthentication in /etc/ssh/sshd_config"
echo ""
