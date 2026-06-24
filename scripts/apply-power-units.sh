#!/usr/bin/env bash
# =============================================================================
# Canonical installer for blacky's battery-aware power-management units.
# =============================================================================
# Single source of truth for the power scripts + systemd units + udev rules.
# Invoked two ways:
#   - during bootstrap, from setup.sh §3c (`bash scripts/apply-power-units.sh`)
#   - standalone, to (re)apply just these units on a running blacky:
#       ssh blacky 'sudo bash ~/homeassistant/scripts/apply-power-units.sh'
#
# cd_deploy.py only applies HA-relevant changes (config/, compose) — it pulls
# this file but never runs it, so OS-level units are (re)installed via this
# script. Idempotent: safe to re-run.
#
# Behaviour:
#   - On AC loss (udev): 1h shutdown timer + a pre-shutdown warn timer (T+55m).
#   - Telegram across the whole sequence (AC lost / 5-min warning / shutting
#     down now / AC restored-cancelled), plus the <=20% emergency watchdog.
#   - homeassistant-stack.service force-starts the compose stack on every boot
#     (the shutdown paths `docker stop` containers, which `unless-stopped` will
#     NOT auto-restart — this closes that gap).
# =============================================================================
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "apply-power-units.sh: must run as root (use sudo)" >&2
    exit 1
fi

# Telegram notifier (Bot API; creds from HA secrets.yaml — same creds cd_deploy.py uses).
# Fire-and-forget: must never fail its caller (it runs in the shutdown path).
cat > /usr/local/bin/notify-telegram.sh << 'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
SECRETS=/home/yossi/homeassistant/config/secrets.yaml
MSG=${1:-}
[[ -z "$MSG" ]] && exit 0
get_secret() { grep -E "^$1:" "$SECRETS" 2>/dev/null | head -1 | sed -E "s/^$1:[[:space:]]*//; s/^[\"']//; s/[\"']$//"; }
TOKEN=$(get_secret telegram_bot_token)
CHAT=$(get_secret telegram_chat_id)
if [[ -z "$TOKEN" || -z "$CHAT" ]]; then
    logger -t notify-telegram "no telegram creds in secrets — skipping: $MSG"
    exit 0
fi
curl -sf --max-time 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT}" \
    --data-urlencode "text=${MSG}" >/dev/null 2>&1 \
    || logger -t notify-telegram "send failed: $MSG"
SCRIPT
chmod +x /usr/local/bin/notify-telegram.sh

cat > /usr/local/bin/on-battery.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
logger -t on-battery "AC lost — starting 1-hour shutdown timer"
systemctl stop battery-shutdown-timer.timer 2>/dev/null || true
systemctl stop battery-shutdown-warn.timer  2>/dev/null || true
systemd-run --unit=battery-shutdown-timer --on-active=3600 \
    /usr/local/bin/shutdown-if-on-battery.sh
# Pre-shutdown heads-up 5 min before the 1h deadline (3600 - 300).
systemd-run --unit=battery-shutdown-warn --on-active=3300 \
    /usr/local/bin/battery-shutdown-warn.sh
/usr/local/bin/notify-telegram.sh "⚠️ blacky: AC power LOST. Running on battery — graceful shutdown in 1h unless AC restored. Plug back in to cancel." || true
logger -t on-battery "Timer started"
SCRIPT
chmod +x /usr/local/bin/on-battery.sh

cat > /usr/local/bin/on-ac.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
if systemctl stop battery-shutdown-timer.timer 2>/dev/null; then
    systemctl stop battery-shutdown-warn.timer 2>/dev/null || true
    logger -t on-ac "AC restored — timer cancelled"
    /usr/local/bin/notify-telegram.sh "✅ blacky: AC restored — shutdown cancelled." || true
else
    systemctl stop battery-shutdown-warn.timer 2>/dev/null || true
    logger -t on-ac "AC restored (no timer active)"
fi
SCRIPT
chmod +x /usr/local/bin/on-ac.sh

cat > /usr/local/bin/battery-shutdown-warn.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
STATUS=$(cat /sys/class/power_supply/BAT0/status 2>/dev/null || echo Unknown)
[[ "$STATUS" != "Discharging" ]] && { logger -t battery-shutdown "warn: AC present — no warning"; exit 0; }
CAPACITY=$(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null || echo 100)
logger -t battery-shutdown "pre-shutdown warning (${CAPACITY}%) — ~5 min to shutdown"
/usr/local/bin/notify-telegram.sh "⏳ blacky: still on battery (${CAPACITY}%) — graceful SHUTDOWN in ~5 min unless AC restored NOW." || true
SCRIPT
chmod +x /usr/local/bin/battery-shutdown-warn.sh

cat > /usr/local/bin/shutdown-if-on-battery.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
STATUS=$(cat /sys/class/power_supply/BAT0/status 2>/dev/null || echo Unknown)
[[ "$STATUS" != "Discharging" ]] && { logger -t battery-shutdown "AC present — no shutdown"; exit 0; }
CAPACITY=$(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null || echo 100)
logger -t battery-shutdown "1h on battery (${CAPACITY}%) — shutting down"
/usr/local/bin/notify-telegram.sh "🔌 blacky: 1h on battery (${CAPACITY}%) — SHUTTING DOWN NOW. Stack auto-starts on next boot." || true
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
        /usr/local/bin/notify-telegram.sh "🔋 blacky: battery ${CAPACITY}% (≤20% emergency floor) — SHUTTING DOWN NOW. Stack auto-starts on next boot." || true
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

# Boot-time stack recovery. The battery-shutdown paths (shutdown-if-on-battery.sh,
# battery-watchdog.sh) call `docker stop` before poweroff, which marks containers
# explicitly-stopped — so `restart: unless-stopped` deliberately will NOT bring them
# back on the next boot. This oneshot force-starts the compose stack on every boot
# (idempotent: a no-op if everything is already up). Runs as yossi (owns the repo +
# in the docker group), same identity cd_deploy.py uses for compose.
cat > /etc/systemd/system/homeassistant-stack.service << 'UNIT'
[Unit]
Description=Bring up the Home Assistant docker compose stack on boot
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
User=yossi
Group=docker
WorkingDirectory=/home/yossi/homeassistant
ExecStart=/usr/bin/docker compose up -d
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/udev/rules.d/99-power.rules << 'RULES'
SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ATTR{online}=="0", \
    RUN+="/bin/systemd-run --no-block /usr/local/bin/on-battery.sh"
SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ATTR{online}=="1", \
    RUN+="/bin/systemd-run --no-block /usr/local/bin/on-ac.sh"
RULES
udevadm control --reload-rules

systemctl daemon-reload
systemctl enable battery-watchdog.service
systemctl restart battery-watchdog.service   # pick up script changes (no-op-safe on first run)
systemctl enable homeassistant-stack.service # boot recovery; not started here (stack may not be up yet during bootstrap)

echo "power units installed: 1h timer + warn (T+55m) + 20% emergency floor, Telegram alerts, boot-time stack recovery"
