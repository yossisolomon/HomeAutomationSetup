# HA-Liveness Grafana Alert — Design

> Add an independent "Home Assistant is down" alert that reaches Telegram, closing
> a monitoring gap: Grafana currently alerts on CPU/RAM/disk/battery but **nothing
> tells you when HA itself is down**, and Prometheus doesn't scrape HA at all. This
> is the standing liveness signal — distinct from backlog #17 (CD), which only
> alerts on *deploy* failures.

## Problem

`grafana/provisioning/alerting/rules.yml` has CPU/RAM/disk/battery rules wired to
the `blacky-notify` Telegram contact point, but no HA-up check. Prometheus scrapes
only `prometheus`/`node-exporter`/`cadvisor` — HA isn't a target. So if HA crashes
or wedges, no alert fires.

## Design

Reuse what already exists rather than adding a scrape target or exporter:

- **Metric:** the host metrics timer (`ha-battery-metrics.sh`, every 60 s, already
  writing to the node_exporter textfile collector) gains a `curl -sf :8123` probe
  and writes an `ha_up` gauge (1/0) via an atomic temp-then-rename. **Key property:**
  it runs as a *host* systemd timer, not inside the HA container, so it keeps
  reporting `ha_up=0` precisely when HA is down — the moment the alert must fire.
  Same curl check the compose healthcheck uses. No new Prometheus job needed
  (node_exporter already scrapes the textfile dir).
- **Rule:** `blacky_ha_down` in `rules.yml` — `ha_up < 1` for 2 m, severity
  `critical`, `noDataState: Alerting` (absent series = monitoring broken = treat as
  down). Routes through the existing `blacky-notify` policy → Telegram. No contact
  point or routing change.

### Why not HA's Prometheus integration / a scrape job
That needs a long-lived token and exposes entity metrics we don't want, and a
scrape of HA's own API can't distinguish "HA down" cleanly on a single-target
`up`. The host-side probe is token-free and HA-internals-independent.

## Files
- `setup.sh` (modify) — `ha_up` probe + atomic textfile write in the §3b publisher.
- `grafana/provisioning/alerting/rules.yml` (modify) — `blacky_ha_down` rule.
- `docs/state-of-world.md` (modify) — backlog #18 done.

## blacky apply (no full setup.sh re-run)
1. Update `/usr/local/bin/ha-battery-metrics.sh` on blacky to the new version; the
   existing timer runs it within 60 s → `ha.prom` appears in the textfile dir.
2. Recreate Grafana so it re-provisions `rules.yml`
   (`docker compose up -d grafana`).

## Validation
1. `curl -s localhost:9100/metrics | grep ha_up` on blacky → `ha_up 1`.
2. Grafana → Alerting shows `Home Assistant Down`, state Normal.
3. Stop HA briefly (`docker stop homeassistant`) → within ~2 m the rule fires and a
   Telegram message arrives; `docker start homeassistant` clears it. (Optional live
   test — do once.)
