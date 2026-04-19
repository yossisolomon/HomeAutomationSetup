#!/bin/sh
set -eu

# Copy provisioning to writable tmpfs, then substitute secrets.
# The source mount is :ro and owned by the host user — grafana (uid 472) can't
# write there directly.
cp -r /etc/grafana/provisioning /tmp/grafana-provisioning

sed -e "s|\${TELEGRAM_BOT_TOKEN}|${TELEGRAM_BOT_TOKEN}|g" \
    -e "s|\${TELEGRAM_CHAT_ID}|${TELEGRAM_CHAT_ID}|g" \
    /tmp/grafana-provisioning/alerting/contact_points.yml.tmpl \
    > /tmp/grafana-provisioning/alerting/contact_points.yml

exec /run.sh
