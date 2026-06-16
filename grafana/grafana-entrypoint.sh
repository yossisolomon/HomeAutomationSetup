#!/bin/sh
set -eu

# Copy provisioning to writable tmpfs, then substitute secrets.
# The source mount is :ro and owned by the host user — grafana (uid 472) can't
# write there directly.
#
# rm -rf first: on a plain `docker restart` the container FS (and this /tmp dir)
# persists, so a bare `cp -r SRC DEST` would nest into the existing dir
# (/tmp/grafana-provisioning/provisioning/...) and leave the OLD rendered files in
# place — Grafana would silently keep using stale rules/contact points until a full
# `--force-recreate`. Wiping the target makes every restart re-render from source.
rm -rf /tmp/grafana-provisioning
cp -r /etc/grafana/provisioning /tmp/grafana-provisioning

sed -e "s|\${TELEGRAM_BOT_TOKEN}|${TELEGRAM_BOT_TOKEN}|g" \
    -e "s|\${TELEGRAM_CHAT_ID}|${TELEGRAM_CHAT_ID}|g" \
    /tmp/grafana-provisioning/alerting/contact_points.yml.tmpl \
    > /tmp/grafana-provisioning/alerting/contact_points.yml

exec /run.sh
