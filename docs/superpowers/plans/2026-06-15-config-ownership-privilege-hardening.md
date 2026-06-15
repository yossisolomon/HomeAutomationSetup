# blacky config Ownership + Privilege Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Tasks 1–2 are repo edits (PR via CI); Task 3 is a **controller/user task** (sudo + live blacky, supervised).

**Goal:** Own `config/` as `yossi` and drop HA's `privileged: true` so an unattended `git pull` works on blacky — the prerequisite for backlog #17 (CD). Folds in the remaining #11 git-drift reconciliation and a discoverability fix.

**Spec:** `docs/superpowers/specs/2026-06-15-config-ownership-privilege-hardening-design.md`

**Repo:** `yossisolomon/HomeAutomationSetup`. Work from `/Users/yossi_solomon/dev/HomeAutomationSetup` on branch `feat/config-ownership-hardening`. blacky repo: `~/homeassistant/`.

---

## Task 1: Repo edits (compose + setup.sh) — DONE on branch

- [x] **Drop `privileged: true`** from the `homeassistant` service in `docker-compose.yml` and replace the stale "privileged is recommended" comment with the real rationale (no local hardware; Zigbee is z2m's; only the two ro mounts needed).
- [x] **`setup.sh` §4d:** split HA out of the root-owned group — `mkdir -p ${HA_DIR}/config` then `chown -R "${MAIN_USER}:${MAIN_USER}" "${HA_DIR}/config"`, with a comment explaining HA reads-only + gitignored runtime files. ESPHome/Portainer unchanged.
- [ ] **Verify locally:** `docker compose config >/dev/null && echo OK` (parses with privileged removed); `bash -n setup.sh && echo OK` (syntax).

## Task 2: Discoverability fix — DONE on branch

- [x] **`AGENTS.md`** sub-topic table: add rows for `docs/state-of-world.md` (marked "read first"), `docs/automation-architecture.md`, `docs/automations.md`, `docs/superpowers/{specs,plans}/`.
- [x] **`CLAUDE.md` → `AGENTS.md` symlink** at repo root (`ln -s AGENTS.md CLAUDE.md`) so the harness auto-loads the guide.
- [ ] **state-of-world #10/#11:** mark #10 done (chown + setup.sh + privileged drop), note #11 reconciliation folded into the migration runbook below.

## PR go-live (controller/user — needs `gh` + green CI)

- [ ] Commit in logical chunks (compose+setup.sh hardening; AGENTS.md+symlink+state-of-world docs).
- [ ] `git push -u origin feat/config-ownership-hardening` → open PR → `gh pr checks --watch` (all four green) → squash-merge.

## Task 3: blacky one-time migration (controller/user — sudo + supervised)

> Do **after** the PR merges. blacky is behind `main`; the catch-up pull crosses the HACS-untrack + z2m-config-move commits, so it needs supervision — do **not** treat disappearing `config/custom_components/*/` as data loss.

- [ ] **Step 1 — chown:** `ssh blacky 'sudo chown -R yossi:yossi ~/homeassistant/config'`; confirm `ssh blacky "stat -c '%U' ~/homeassistant/config"` → `yossi`.
- [ ] **Step 2 — supervised catch-up pull (#11):** verify clean tree first (`git -C ~/homeassistant status -s` — the only expected diff is the live z2m/custom_components state), then `git -C ~/homeassistant pull --ff-only origin main`. The HACS-untrack commit removes `config/custom_components/*/` from tracking → the working-tree dirs may be deleted; **HACS reinstalls them from `hacs-manifest.yaml`** — do not blind-`checkout` them back. If the pull refuses (non-ff / local edits), stop and inspect; do not force.
- [ ] **Step 3 — recreate HA without privileged:** `ssh blacky 'cd ~/homeassistant && docker compose up -d homeassistant'`. Confirm `docker inspect homeassistant --format '{{.HostConfig.Privileged}} {{.State.Health.Status}}'` → `false healthy` (allow ~90s start_period).
- [ ] **Step 4 — verify HA functional:** HA UI loads on :8123; battery `command_line`/sensor still reads `/sys`; HACS integrations (Xiaomi MIoT, LocalTuya) load.
- [ ] **Step 5 — prove unattended pull:** `ssh blacky 'sudo -u yossi git -C ~/homeassistant pull --ff-only'` runs with **no permission-denied** (up-to-date is fine). This is the gate that unblocks #17.

---

## Self-Review

- **Spec coverage:** privileged drop (T1) ✓; chown in setup.sh (T1) ✓; one-time chown + recreate (T3) ✓; #11 supervised catch-up with HACS-reinstall caveat (T3 Step 2) ✓; discoverability AGENTS.md + symlink (T2) ✓; verification = ownership + Privileged=false + healthy + clean pull (T3 Steps 1,3,5) ✓.
- **Risk:** the catch-up pull is the only non-trivial step — mitigated by "supervised, don't force, HACS reinstalls" guidance and the memory hazard note in `[[blacky-smart-home-project]]`.
- **Reversibility:** privileged can be re-added in one line; chown is harmless (HA-as-root writes regardless). No automation behavior changes.
