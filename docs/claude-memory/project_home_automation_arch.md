---
name: home-automation-arch
description: HomeAutomationSetup — automation engine architecture spec (approved) + the sub-project backlog/sequence discovered while brainstorming it
metadata: 
  node_type: memory
  type: project
  originSessionId: ddf77003-9497-43cd-ac21<REDACTED-ID>d9b
---

Spec 1 (automation architecture + state-of-world doc rewrite) approved 2026-06-05.
Lives at `~/dev/HomeAutomationSetup/docs/superpowers/specs/2026-06-05-home-automation-architecture-design.md`.
Plan: `~/.claude/plans/my-home-automation-setup-fuzzy-wave.md`. Builds on [[blacky-smart-home-project]].

**Locked decisions:**
- Engine = **hybrid**: HA YAML + blueprints for simple automations; Node-RED only for
  complex/stateful/multi-input flows.
- Node-RED diff hygiene: `node-red-contrib-flow-manager` (per-domain files) + `jq` coord
  normalizer + externalized Function-node JS (ESLint) + file-backed `contextStorage`.
- **CTA channel = Telegram** (live; two-way via `telegram_callback` inline buttons; works
  remotely without exposing HA). HA companion app deferred to after remote-access decision.
- Self-documenting `docs/automations.md` ToC: AUTOGEN block generated from a required
  per-automation `# meta: intent=…; waf=…; mode=auto|cta` annotation; enforced by a
  versioned pre-commit hook (`core.hooksPath=scripts/git-hooks`) that lints, validates meta
  presence + unique names, and regenerates the ToC.

**Why:** scope kept to architecture + doc only so the first working automation lands on a
clean, reviewable, self-documenting foundation. Philosophy: unsure → call-to-action, not
fragile full automation.

**Workflow now ENFORCED (2026-06-15):** `main` is branch-protected — every change goes via
feature branch → PR → green CI → **squash-merge**. Direct push to `main` is rejected (admins too).
CI = `.github/workflows/ci.yml`, 4 parallel jobs `lint`/`toc`/`pytest`/`normalizer` (required-check
contexts are the **bare job names**, NOT `CI / <job>`). So next session: **branch + PR, never commit
to main.** blacky pulls `origin/main`. See [[blacky-smart-home-project]] for blacky-side ops.

**Buzzer preference:** purifier beep-on-change is silenced per-unit via `switch.*_alarm_p_6_1`
(one-off manual toggle, device-persisted). User does NOT want a buzzer-off guard forced into the
automations — keep it manual so they can change their mind.

**Sub-project backlog (each its own future spec, rough sequence):**
1. ✅ **Climate flagship part A — DONE + live (2026-06-15):** air-quality purifier control, 3 units
   (Living 4 Pro = `fan.*` power; Master + Mamad 4 Compact = `switch.*` power + `select.*` mode),
   per-area night windows, global `any_window_open` gate (balcony `windowlivingroom_contact` + office
   `windowyossi_contact`, fail-open) + per-sensor include toggles, restore-based kill switch
   `input_boolean.purifier_auto_enable`. Pro favorite_speed is RPM (min 200 / max 2300). Mamad
   Compact device id = `828351147`. **Part B still open:** window-vs-AC CTA + CO2/ventilation.
1b. **CD — blacky safe auto-deploy** (= backlog #17). ✅ **DONE + LIVE (2026-06-18):**
   `scripts/cd_deploy.py` + `/etc/cron.d/cd-deploy` (every 2 min as yossi). fetch origin/main →
   check_config in real container → change-detect (reload-safe → HA reload via admin `cd_deploy_token`;
   heavier → `docker compose --force-recreate`) → rollback + Telegram on failure. E2E verified
   (scene.reload, no restart) + autonomous cron deploy confirmed. Replaced manual `make check`.
   ✅ **#10 (config ownership/privilege) + #18 (HA-down Grafana alert) + #19 (grafana provisioning/telegram
   hardening) all done + live.** Smart-home infra backlog #10/#17/#18/#19 cleared this stretch.
   ✅ **#10 unblocked + live (2026-06-16):** privileged dropped, config/ yossi-owned, unattended pull works.
   Also done+live: **#18** HA-down Grafana alert (native /api/prometheus scrape, dedicated non-admin monitoring
   token in gitignored `prometheus/secrets/`) + **#19** grafana provisioning-reload + telegram-retry hardening.
   #17 design (change-detect reload-vs-restart, rollback, **separate admin** CD token, cron.d) is in
   `docs/state-of-world.md` §7 #17 — that doc (now surfaced in the repo's AGENTS.md sub-topic table, which is
   symlinked as CLAUDE.md) is the live backlog source of truth. Workflow: feature branch → PR → green CI → squash-merge → pull on blacky
   → recreate affected containers. **Gotcha:** HA secrets.yaml values are quote-wrapped — strip quotes when
   reading a token into a file. Grafana provisioning only refreshes on restart since the #19 entrypoint fix.
2. IR code-set finder script — ✅ done (per state-of-world); record via Broadlink learn → search IR DB → ID code set.
3. ✅ CUPS print server on blacky (Brother USB laser → LAN driverless IPP).
4. Remote access — Nabu Casa vs Cloudflare tunnel (undecided).
5. Window-open sensing — original Zigbee contacts too fat for sliding-pane gap; office+balcony now paired (TS0203).
6. Boiler cavity temp probe (Dolphin-style internal water temp) → boiler temp notify.
7. Plant-maintenance — 8 Zigbee soil-moisture sensors (2 paired) → watering reminders.

**Corrected device facts (supersede older inventory):** Qingping = WiFi/cloud-MQTT (no BT proxy;
2.4GHz penetrates Mamad even locked). Fans = RF via Broadlink (whole-house). Boiler LocalTuya DONE.
Dropped: ESP32 Totems, Mamad BT proxy + Xiaomi BT thermometers, Sonoff RF Bridge, Shelly 1PM lights,
Shelly Plus heaters, Zigbee TP buttons.
