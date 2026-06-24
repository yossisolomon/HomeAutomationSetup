# Climate Flagship B — Window-vs-A/C CTA + CO2/Ventilation — Design

> Backlog #1, part B. Part A automates the **purifiers** on indoor PM. Purifiers don't touch
> **CO2**, and they stand *down* when a window is open. Part B closes the loop: when indoor air
> degrades, **ask the human (Telegram CTA) to open a window vs run the A/C**, and prompt to
> ventilate when CO2 is high. Philosophy: unsure → CTA, not fragile full automation. The CTA
> blueprint's first real consumer.

## Core model — the decision the CTA encodes

Indoor air degraded (high CO2, or high PM) → **outdoor AQI decides**:

- **Outside clean** → *ventilate*: recommend **open a window** (fresh air flushes CO2/PM; the
  purifier auto-stands-down via Part A's `any_window_open` gate).
- **Outside polluted** → *seal up*: recommend **run the A/C** (recirculate + comfort; don't pull
  in pollution).

**Outdoor temperature** is a comfort tiebreaker: only recommend a window when it's **≤ 26 °C
outside** (tunable). Absolute cap, *not* an outdoor-vs-indoor compare — indoor usually reads low
after the A/C has run, which would wrongly block a window even when it's pleasant out.

## Whole apartment = one unit (not per-area)

`climate.smartir_climate_1581` (MainAC) is a mini-central channelled to
living/master/mamad/office/kitchen — there is **no per-room A/C lever**, so per-area CTAs have no
clear ROI. Part B treats the **whole apartment as a single unit**: one aggregated "air degraded"
signal, one CTA, one cooldown. Dana's room (`climate.danaofficeac`, too far for the central) is
adjacent to the living room → considered part of the same space.

This also lets Part B **reuse Part A's global `binary_sensor.any_window_open`** for the "window
already open?" check — so no new per-area window contacts are needed. The Master/Mamad contacts
arriving with the Shelly blinds simply fold into `any_window_open` (Part A already has their
consider-toggles).

## CTA channel — the existing blueprint (unproven button flow)

`config/blueprints/script/homeassistant/telegram_confirmable.yaml` — 2 inline buttons
(Confirm/Dismiss) + `telegram_callback` round-trip + timeout. **The bot has so far only sent plain
notifications; the inline-button callback flow is unproven.** This CTA is the blueprint's first
real consumer, so the button round-trip is validated as the **first live step** (see Validation)
before the trigger is wired.

The blueprint's `message` input is rendered as a **Jinja template at send time**, so one static
script instance produces a fully dynamic, live message. The two fixed buttons map cleanly to the
binary window-vs-A/C choice; the **message text** carries the recommendation.

## Verified / resolve-live entities

| Role | Entity | Status |
|------|--------|--------|
| CO2 (living) | `sensor.airmonitor2_co2` | live |
| CO2 (master) | `sensor.airmonitorlitemaster_co2` | live |
| CO2 (mamad) | `sensor.mamadairmonitor_co2` | live |
| Indoor PM (per area) | Part A's `binary_sensor.<area>_air_bad` | live |
| Window-already-open | Part A's `binary_sensor.any_window_open` | live |
| A/C (central) | `climate.smartir_climate_1581` | controls **verify on blacky** before enable |
| Outdoor AQI | `sensor.kmutzkin_begin_haifa_and_krayot_israel_yshrl_q_mvtsqyn_bgyn_khyph_vqryvt_air_quality_index` | resolved (live) |
| Outdoor temp | `sensor.kmutzkin_begin_haifa_and_krayot_israel_yshrl_q_mvtsqyn_bgyn_khyph_vqryvt_temperature` (separate WAQI sensor — this integration version exposes temp as its own entity, **not** an attribute) | resolved (live) |
| Telegram chat | `!secret telegram_chat_id` | gitignored secret |

## Thresholds

| Signal | ON | Clear | Notes |
|--------|----|-------|-------|
| CO2 (any of 3 sensors) | ≥ 1400 ppm | ≤ 1000 ppm | hysteretic |
| Outdoor AQI ventilate-OK | ≤ `input_number.outdoor_aqi_ventilate_max` (default 100) | — | "moderate or better" |
| Outdoor temp ventilate-OK | ≤ `input_number.ventilate_max_outdoor_temp` (default 26 °C) | — | absolute cap |

## Template signals — `config/template/climate_cta.yaml` (new)

Same hysteresis-via-`this.state` + fail-safe idiom as `purifier_auto.yaml`.

- `binary_sensor.apartment_co2_high` — ON when **any** CO2 sensor ≥ 1400; clears only when all
  available ≤ 1000. Hysteretic.
- `binary_sensor.apartment_air_degraded` — `apartment_co2_high or living_air_bad or
  master_air_bad or mamad_air_bad`. The CTA trigger term.
- `binary_sensor.outdoor_air_ok` — WAQI AQI ≤ `outdoor_aqi_ventilate_max`, hysteretic.
- `binary_sensor.ventilate_favorable` — `outdoor_air_ok` **and** outdoor temp ≤
  `ventilate_max_outdoor_temp` **and** `any_window_open` is off. The window-vs-A/C decision bit:
  favorable → recommend window, else A/C.
- `binary_sensor.cta_quiet_hours` — now within the global quiet window
  (`input_datetime.climate_cta_quiet_start`..`_end`, default 22:00 → 08:00); wraparound idiom
  from Part A's `<area>_is_night`.

## Helpers

- `input_boolean.climate_cta_enable` — global kill switch (no `initial:` → comes up OFF, persists;
  same pattern as `purifier_auto_enable`).
- `input_number.ac_cool_setpoint` (default 24 °C) — the A/C-button target temperature. **A HA
  dashboard slider tuned in the UI** — NOT a number typed back to the Telegram message (the
  blueprint has no free-text capture). Reply-with-temperature would need a different design; out
  of scope.
- `input_number.outdoor_aqi_ventilate_max` (default 100).
- `input_number.ventilate_max_outdoor_temp` (default 26 °C).
- `input_datetime.climate_cta_quiet_start` (22:00) / `…_quiet_end` (08:00).
- `timer.climate_cta_cooldown` (~2h) — re-prompt rate-limit.

## CTA script — `config/scripts.yaml` (`script.climate_cta`)

`use_blueprint: homeassistant/telegram_confirmable.yaml` with:

- `target_chat: !secret telegram_chat_id`
- `message:` template — CO2/PM reading + worst area, outdoor AQI + temp, and the recommendation
  (window when `ventilate_favorable`, else A/C).
- `confirm_text: "❄️ Run A/C"`, `confirm_action:` `climate.set_hvac_mode: cool` +
  `climate.set_temperature` (target = `input_number.ac_cool_setpoint`) on
  `climate.smartir_climate_1581`.
- `dismiss_text: "🪟 Open window"`, `dismiss_action:` ack notify + `climate.turn_off` the central
  A/C if running (don't fight an open window). Human opens the window manually.
- `timeout_hours: 1` — no action on no-press.

## Automation — `config/automations.yaml` (append, `mode=cta`)

`climate-cta-ventilate`:

- **Trigger:** `binary_sensor.apartment_air_degraded` → `on`.
- **Conditions:** `climate_cta_enable` on **and** `cta_quiet_hours` off **and**
  `timer.climate_cta_cooldown` idle.
- **Action:** `script.climate_cta`, then `timer.start` the cooldown.
- **Meta:** `# meta: intent="when apartment air degrades (CO2/PM), ask via Telegram to open a
  window vs run the central A/C, decided by outdoor AQI + temp"; waf=med; mode=cta`

`waf=med`: acts on the shared central A/C, but only on an explicit button press, bounded by the
kill switch + cooldown + quiet-hours.

## Files

- `config/template/climate_cta.yaml` (new) — the 5 template signals.
- `config/scripts.yaml` (modify) — the `climate_cta` blueprint script.
- `config/automations.yaml` (modify) — append `climate-cta-ventilate`.
- `config/input_boolean.yaml` (modify) — add `climate_cta_enable`.
- `config/input_number.yaml` (new) + `config/timer.yaml` (new) — helpers + cooldown timer.
- `config/input_datetime.yaml` (modify) — quiet-hours pair.
- `config/configuration.yaml` (modify) — `input_number: !include …`, `timer: !include …`.
- `docs/state-of-world.md` (modify) — mark backlog #1 Part B done.
- `docs/automations.md` — regenerated by the ToC pre-commit hook (never hand-edited).

## Validation

- **First live step — prove the button flow** (unproven): with `climate_cta_enable` on, run
  `script.climate_cta` manually → confirm both inline buttons render, each tap emits a
  `telegram_callback` and runs the right branch (A/C cool @ setpoint / A/C off + ack). De-risks the
  blueprint's first callback use before wiring the trigger.
- `make lint` (yamllint) + `make toc` (meta present + alias unique — pre-commit hook enforces).
- `make check` — full HA `check_config` in the `homeassistant` container on blacky → passes.
- Live (blacky, Dev Tools): force `apartment_co2_high` (state override) → CTA fires only when
  enabled, not in quiet-hours, cooldown idle. Set the outdoor AQI / temp helpers low/high →
  message recommendation flips (window ↔ A/C). Cooldown blocks a second prompt within 2h;
  quiet-hours suppresses entirely.

## Out of scope (later)

- Reply-to-CTA-with-a-temperature (needs preset buttons or a text-callback handler).
- Per-room A/C (no hardware lever).
- Office/Dana-room as independent trigger areas (no CO2/PM sensor there).
