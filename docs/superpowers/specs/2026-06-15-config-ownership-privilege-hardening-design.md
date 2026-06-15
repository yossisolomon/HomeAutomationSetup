# blacky config Ownership + Privilege Hardening — Design

> Make `config/` owned by the main user instead of `root`, and drop
> `privileged: true` from the Home Assistant container. This unblocks an
> unattended `git pull` on blacky (the prerequisite for backlog **#17 CD**) and
> removes an unnecessary container privilege. Covers backlog **#10** and folds in
> the remaining **#11** git-drift reconciliation. Pure infra/hardening — no
> automation behavior changes.

## Problem

`config/` on blacky is `root:root` because the official HA image runs as root and
created the bind-mounted tree as root. Two consequences:

- **Unattended `git pull` can't work.** A cron-driven pull running as `yossi`
  can't overwrite root-owned tracked files (`automations.yaml`, `scripts.yaml`,
  `configuration.yaml`, `template/`, …). This blocks the CD poller (#17).
- **`privileged: true` on the HA service is unnecessary and over-broad.** It was
  copied from upstream's "in case you need USB/BT" advice, but this HA has zero
  local-hardware integrations.

blacky is also still **behind `main`** and was never fully reconciled after the
HACS-untrack and z2m-config-move commits (#11), so the first catch-up pull needs
care.

## Why ownership is safe to flip

- HA **only reads** the git-tracked YAML (automations, scripts, scenes, inputs,
  templates, `configuration.yaml`) — verified: they're pulled via `!include` /
  `!include_dir_merge_list`, and the convention (`config/AGENTS.md`) is that they
  are git-authored, never UI-authored. So HA-as-root reading yossi-owned files is
  fine, and there are **no runtime rewrites** to re-conflict the working tree.
- The files HA **does** create as root — `.storage/`, `*.db`, `*.log`,
  `secrets.yaml`, `custom_components/*/` — are all **gitignored**, so their
  ownership is irrelevant to git. Root can keep writing them regardless of the
  dir owner.

## Why privileged is safe to drop

HA passes **no `devices:`**, needs no capabilities, and its only host access is
two read-only mounts (`/run/dbus:ro`, `/sys/class/power_supply:ro`) that work
without privileged. Zigbee (the one piece of real hardware) belongs to the
`zigbee2mqtt` container, which holds the dongle via its own `devices:` entry.
Recreating the HA container is a brief restart (Z2M + mosquitto stay up; Zigbee
state recovers via retained MQTT).

## Scope

**In:**
- Drop `privileged: true` from the `homeassistant` service in `docker-compose.yml`
  (+ correct the stale comment).
- `setup.sh`: own `config/` as `${MAIN_USER}` (recursive chown) so fresh rebuilds
  start correctly owned.
- One-time blacky migration: `sudo chown -R yossi:yossi config`, supervised
  catch-up pull, recreate HA without privileged, verify.
- **Discoverability fix** (root cause of this work being hard to find): surface
  `docs/state-of-world.md` (+ its backlog) and the architecture/registry docs in
  `AGENTS.md`, and add a `CLAUDE.md -> AGENTS.md` symlink so the harness auto-loads
  the guide.

**Out (later / own specs):**
- **#17 CD** — the auto-deploy poller itself. This spec only removes its blocker.
- HA-liveness Grafana alert (`ha_up`) — tracked separately; the "HA is down" signal
  must come from Grafana, independent of CD.

## Design

### `docker-compose.yml`
Remove the `privileged: true` line; replace the misleading "privileged is
recommended" comment with the actual rationale (no local hardware; Zigbee is
z2m's; only the two ro mounts are needed).

### `setup.sh` (§4d Docker data volume permissions)
HA, ESPHome, Portainer were treated as "root-owned services — just `mkdir -p`".
Split HA out: still `mkdir -p`, then `chown -R "${MAIN_USER}:${MAIN_USER}"
"${HA_DIR}/config"`, with a comment explaining HA-reads-only / gitignored-runtime
-files. Idempotent, survives rebuilds. ESPHome/Portainer unchanged.

### blacky one-time migration (runbook, in the plan doc)
1. `sudo chown -R yossi:yossi ~/homeassistant/config`.
2. Pull `docker-compose.yml` + recreate HA: `docker compose up -d homeassistant`;
   confirm it comes up healthy **without** privileged (healthcheck on :8123) and
   the battery `command_line` sensor still reads `/sys`.
3. **Supervised catch-up (#11):** blacky is behind `main`; the HACS-untrack commit
   removes `config/custom_components/*/` from tracking. A `git pull --ff-only` will
   delete those paths from the working tree, but they are **reinstalled by HACS via
   `hacs-manifest.yaml`** — do **not** treat their disappearance as data loss, and
   do **not** blind-`checkout` them back. Verify HA + HACS integrations load after.
4. Confirm a subsequent `git pull` as `yossi` succeeds with no permission errors.

### Discoverability
`AGENTS.md` sub-topic table gains rows for `docs/state-of-world.md` (marked "read
first"), `docs/automation-architecture.md`, `docs/automations.md`, and the
`docs/superpowers/{specs,plans}/` convention. New root `CLAUDE.md` symlink →
`AGENTS.md`.

## Files
- `docker-compose.yml` (modify) — drop `privileged: true` + comment.
- `setup.sh` (modify) — recursive chown of `config/` to main user in §4d.
- `AGENTS.md` (modify) — sub-topic rows for state-of-world / architecture /
  registry / specs.
- `CLAUDE.md` (new symlink → `AGENTS.md`).
- `docs/state-of-world.md` (modify) — mark #10 done, fold #11 status.

## Validation
1. `docker compose config` parses; `make lint` clean (CI `lint`/`toc`/`pytest`/
   `normalizer` all green on the PR).
2. On blacky after migration: `stat -c '%U' config` → `yossi`; HA container
   `State.Health.Status` = healthy and `HostConfig.Privileged` = false
   (`docker inspect homeassistant`); battery sensor populated in HA.
3. `sudo -u yossi git -C ~/homeassistant pull --ff-only` runs clean (no
   permission-denied), and HACS integrations still load.

## Out of scope (later specs)
- **#17 CD** poller (depends on this).
- HA-liveness `ha_up` metric + Grafana HA-down alert.
