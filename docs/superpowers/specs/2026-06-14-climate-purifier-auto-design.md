# Climate Flagship A — Air-Quality-Driven Purifier Control — Design

> Backlog #1, part A. Replace the Xiaomi app's daily purifier schedule with an
> air-quality-driven, time-aware, multi-sensor HA automation. The first real automation —
> proves the architecture pipeline (engine rubric, `meta` annotations, ToC hook) end to end.
> Part B (window-vs-AC CTA + CO2/ventilation) is a separate, later spec.

## Scope

**In:** automatic on/off + mode control of **all three** purifiers (Living 4 Pro, Master 4
Compact, Mamad/child 4 Compact), driven by indoor particulate levels (PM2.5 + PM10) fused
from both the Qingping monitors and the purifiers' own internal sensors, with per-area
day/night behavior, a cross-room coordination rule, and **window-open gating** — a purifier
doesn't run against an open window. Window gating uses contact sensors on the living-room
balcony door + Yossi's office window (both Zigbee, on hand).

The 3rd purifier (Mamad = child's room) and the window sensors are pulled into A (was the
Part-B "seam") because the hardware is ready and gating from day one lands a cleaner, more
solid result than a half-feature that ignores open windows.

**Out (deferred to Part B / later):** the **window-vs-AC call-to-action** (decide AC vs open
window on outdoor AQ — the office-window sensor is wired/exposed in A but its CTA consumer
lands in B), CO2 / ventilation (purifiers don't remove CO2), the ACs themselves, presence.

## Engine decision

**HA YAML + template/helper entities** (not Node-RED). Chosen during brainstorming: it
keeps the first automation lower-risk and proves the pipeline without standing up the whole
Node-RED stack. The logic — fuse two sensors per area, day/night branching, Pro-protects-
bedroom coordination — is expressible with template `binary_sensor`s + a few automations.
Promote to Node-RED later only if the coordination outgrows YAML.

## Verified devices (blacky entity registry)

Areas reuse the **existing HA Areas** — no new "zone" taxonomy. The three already exist:
**Living**, **Master Bedroom**, **Mamad** (the child's room). Helper/sensor names below use
the area slug (`living` / `master` / `mamad`).

| Area (HA) | Purifier power | Purifier mode/speed | Qingping PM | Purifier internal PM |
|-----------|----------------|---------------------|-------------|----------------------|
| **Living** | 4 Pro — `fan.zhimi_sg_974057338_vb4_s_2_air_purifier` on/off via `fan.turn_on`/`fan.turn_off` | `fan.set_preset_mode` (`Auto/Sleep/Manual/Level`); speed `number.…_vb4_favorite_speed_p_9_2` | `sensor.airmonitor2_pm25`, `sensor.airmonitor2_pm10` | `sensor.zhimi_sg_974057338_vb4_pm2_5_density_p_3_4`, `sensor.zhimi_sg_974057338_vb4_pm10_density_p_3_8` |
| **Master Bedroom** | 4 Compact — `switch.xiaomi_sg_828358399_cpa4_on_p_2_1` (clean power on/off) | `select.xiaomi_sg_828358399_cpa4_mode_p_2_4` (`Auto/Sleep/Manual`); level `number.xiaomi_sg_828358399_cpa4_favorite_level_p_9_11` | `sensor.airmonitorlitemaster_pm25`, `sensor.airmonitorlitemaster_pm10` | `sensor.xiaomi_sg_828358399_cpa4_pm2_5_density_p_3_4` (no PM10) |
| **Mamad** (child) *(2nd Compact online ~tomorrow)* | 2nd 4 Compact — mirrors Master (its own `switch.…_on_p_*`) | mirrors Master (`select` mode + `number` level) | `sensor.mamadairmonitor_pm25`, `sensor.mamadairmonitor_pm10` (own Qingping, **live now**) | internal PM2.5 (no PM10) |

**Power control differs by model:** the Pro is a `fan` entity — power is `fan.turn_on`/
`fan.turn_off` (idempotent); the Compacts have no fan entity, so power is the `switch.…_on`
entity (idempotent). Neither needs the old toggle-button hack. The original "Pro is always
on" assumption is dropped — every purifier has explicit, addressable power.

The Compacts' internal sensor lacks PM10, so those areas take PM10 from the Qingping only.

**Window sensors** (Zigbee contact, on hand — paired during implementation): **Living
balcony door**, **Yossi's office window**, and (optionally now) **Mamad window**. They are
**not** per-area gates — they feed one **global** signal: *any considered window open →
suppress all filtering* (and later the AC). An open window anywhere means the purifier is
just wasting filter life and pulling in humidity, so the whole feature stands down. See the
`any_window_open` helper below.

Each sensor has an **include toggle** so an unreliable one can be dropped from the global OR
without unpairing it — important for **Mamad**: the safe-room acts as a Faraday cage (flaky
Zigbee), and during "blast mode" the window wings come off for weeks, so its contact reads
meaningless. Toggle it out and it stops affecting anything.

### Control verification (gate before wiring automations)

Before any automation acts on a device, each control is exercised manually (Dev Tools →
Services, or the entity card) and physically confirmed — this is the first live step, and
Yossi has offered to verify the hardware:

- Pro: `fan.turn_on`/`fan.turn_off`, `fan.set_preset_mode` Auto/Sleep, set `favorite_speed`.
- Each Compact: `switch` on/off, `select` mode Auto/Sleep, set `favorite_level`.
- Window sensors: open/close each → confirm the `binary_sensor` flips.

Only controls that pass get wired. (Resolves the "are these the right controls?" question —
we prove them on the real devices first rather than trusting the registry alone.)

## Thresholds (µg/m³; trigger on **either** pollutant)

| Pollutant | ON (≥) | OFF / clear (≤) | VERY-HIGH (= 2× ON) |
|-----------|--------|------------------|---------------------|
| PM2.5     | 25     | 12               | 50                  |
| PM10      | 50     | 30               | 100                 |

Hysteresis: an area's `air_bad` turns **on** at the ON line and stays on until **all** its
sensors fall to the OFF line (implemented with the template `this.state` self-reference
pattern). VERY-HIGH is the night bedroom-escalation gate.

## Helper entities

- `input_boolean.purifier_auto_enable` — **the master on/off for this whole feature.**
  When **on** (the normal state), the automations run: they turn the purifiers on/off and
  pick modes for you based on air quality + time of day. When **off**, every purifier
  automation does nothing — the purifiers stay exactly where you last left them and you
  control them by hand (Xiaomi app / HA card). It's the "stop being clever, leave my
  purifiers alone" switch — flip it off if the automation ever misbehaves or you want full
  manual control, flip it back on to resume. One toggle, affects all three areas.
- **Night windows — one pair per area** (each independently UI-tunable; nice to set once but
  they can diverge, so they stay separate):
  - `input_datetime.living_night_start` / `…_night_end` — default 22:00 → 07:00.
  - `input_datetime.master_night_start` / `…_night_end` — default 22:00 → 07:00.
  - `input_datetime.mamad_night_start` / `…_night_end` — earlier bedtime, default ~18:00 → 07:00.
- **Window include toggles** — one `input_boolean` per window sensor, controlling whether it
  counts toward `any_window_open`:
  - `input_boolean.window_consider_living_balcony` (default on)
  - `input_boolean.window_consider_office` (default on)
  - `input_boolean.window_consider_mamad` (default **off** until the Mamad sensor proves
    reliable; flip off again during blast mode).
- Template `binary_sensor`s (in `config/template/purifier_auto.yaml`):
  - `binary_sensor.any_window_open` — **global.** True if **any** window whose include
    toggle is on currently reads open. This is the single window gate for every purifier
    (and, in B, the AC). A toggled-out sensor is ignored entirely.
  - `binary_sensor.<area>_air_bad` — any available sensor PM2.5 ≥ 25 **or** PM10 ≥ 50;
    clears when all ≤ OFF (12 / 30). Hysteretic via `this.state`.
  - `binary_sensor.<area>_air_very_bad` — PM2.5 ≥ 50 on **both** internal + Qingping (where
    both exist) **or** Qingping PM10 ≥ 100. (Living needs only `air_bad`.)
  - `binary_sensor.<area>_is_night` — now within that area's own night window
    (`<area>_night_start`..`<area>_night_end`).
  - `binary_sensor.<area>_should_purify` — `air_bad and purifier_auto_enable
    and not any_window_open`. **The window gate is live in A and global** — any considered
    window open suppresses every purifier, not just one area's. Same term for all areas.

## Behavior

| | **Day** (outside night window) | **Night** (within night window) |
|---|---|---|
| **Living Pro** | `should_purify` → ON, preset **Auto** (device self-regulates). Clear → OFF. | Baseline **OFF**. Living's **own** `air_bad` → ON preset **Auto** (gentle). A **bedroom** `air_bad` → ON **high Manual** (proactive pre-clear; Pro is away from bedrooms). Both → high Manual wins. Clear → OFF. |
| **Master Compact** | `should_purify` → ON (`switch` on), preset **Auto**. Clear → OFF. | ON, preset **Sleep** as the every-night baseline (replaces the app schedule). Escalate to **Auto** only on `air_very_bad`; drop back to Sleep on recovery. |
| **Mamad Compact** (child) | `should_purify` → ON (`switch` on), preset **Auto**. Clear → OFF. | Same pattern as Master — **Sleep** baseline, escalate to **Auto** only on `air_very_bad` — but on the **Mamad** night window (~18:00 start, earlier bedtime). |

The Pro is **off at night by default** (matches the current midnight-off habit; the
`input_datetime` night window lets it be tuned to 22:00 or midnight from the UI).

**Coordination (your rule):** at night the Pro responds *first* and proportionately — its
**own** bad air gets a gentle **Auto**, but **either bedroom** (Master *or* Mamad) going
`air_bad` (≥ ON) forces the Pro to **high Manual** to pre-clear, while that bedroom's Compact
stays on quiet Sleep. A Compact only escalates above Sleep at `air_very_bad` (≥ 2× ON). The
Pro buys air-cleaning before the bedroom unit has to get loud and wake anyone.

(All of this is under the `purifier_auto_enable` master switch described in Helpers — off →
every automation no-ops and the purifiers stay on manual control.)

## Automations (`config/automations.yaml`, currently `[]`)

Each carries the required `# meta:` annotation and a domain-prefixed unique alias:

- `climate-purifier-living` — `# meta: intent="auto-run living air purifier on indoor PM, ramp at night to protect bedrooms, stand down when any window open"; waf=med; mode=auto`
- `climate-purifier-master` — `# meta: intent="auto-run master-bedroom purifier; sleep baseline at night, escalate only when air is very bad"; waf=med; mode=auto`
- `climate-purifier-mamad` — `# meta: intent="auto-run child-room purifier; sleep baseline on early night window, escalate only when air is very bad"; waf=med; mode=auto`

Structure: per-purifier automation triggered by its area helpers + the `is_night` flag +
(for the Pro) **both** bedrooms' `air_bad`/`air_very_bad` flags, branching with `choose:`
over day/night and air state into the actions in the matrix above. `waf=med` — they act on
bedroom devices at night, but the Sleep baseline + VERY-HIGH gate + kill switch bound the
blast radius. The Mamad automation is the Master pattern cloned onto the `mamad_*` night
window. All three automations share the global `any_window_open` gate (via `should_purify`),
so the **office** window — like every considered window — already suppresses filtering in A;
its *additional* role in the window-vs-AC CTA lands in Part B.

## Files

- `config/template/purifier_auto.yaml` (new) — the per-area air `binary_sensor`s + the global
  `any_window_open`. Picked up by the existing `template: !include_dir_merge_list template/`.
  `any_window_open` ORs each window's real Zigbee contact entity **gated by its include
  toggle** (`window_consider_*`); entity ids resolved at implementation once paired.
- `config/input_boolean.yaml` (new) — `purifier_auto_enable` + the three `window_consider_*`
  include toggles.
- `config/input_datetime.yaml` (new) — three night-window pairs, one per area
  (`living_*` / `master_*` / `mamad_*`).
- `config/configuration.yaml` (modify) — add `input_boolean: !include input_boolean.yaml`
  and `input_datetime: !include input_datetime.yaml`.
- `config/automations.yaml` (modify) — replace `[]` with the **three** purifier automations.
- Window sensors: paired in the existing Zigbee stack (no repo file); their `binary_sensor`
  entity ids are wired into `any_window_open` once paired.
- `docs/automations.md` — regenerated by the pre-commit ToC hook (not hand-edited).
- `docs/state-of-world.md` (modify) — mark #1 part A done (incl. 3rd purifier + window
  gating); note the remaining part B = window-vs-AC CTA + CO2/ventilation.

## Validation

- `make lint` (yamllint over `config/`) and `make toc` (ToC regenerates; meta present, alias
  unique — the pre-commit hook enforces both).
- `make check` — full HA config check in the `homeassistant` container on blacky → passes.
- **Control verification first** (the gate above): every Pro/Compact control + each window
  sensor exercised and physically confirmed before its automation is enabled.
- Live on blacky (real devices):
  1. Toggle `input_boolean.purifier_auto_enable` off → automations no-op (Dev Tools → trace).
  2. Temporarily lower an area's ON threshold (or use a Dev Tools template) so `air_bad`
     flips → confirm the Pro turns on Auto (day) and the Compact responds per matrix.
  3. Set an area's night window to "now" → confirm night behavior: Compact to Sleep
     baseline, Pro proactive ramp on bedroom `air_bad`. Repeat for the `mamad_*` window.
  4. Drive a bedroom to `air_very_bad` (Dev Tools state override) → confirm that bedroom's
     Compact escalates Auto, then returns to Sleep on recovery.
  5. **Window gate (global):** with multiple areas `air_bad`, open the balcony contact →
     confirm `any_window_open` flips and **every** purifier stands down; close it → all
     resume. Then flip `window_consider_office` off and open the office window → confirm it
     is ignored (purifiers stay on); flip back on → it gates again.
  6. Confirm idempotency: re-triggering with unchanged state doesn't thrash the devices
     (mode `restart`/state-guarded actions).

## Out of scope (later specs)

- Part B: the **window-vs-AC CTA** (use the now-installed window sensors + outdoor AQ to
  prompt "open the window vs run the AC"), CO2 / ventilation logic.
- AC control, presence-based modes.
- Node-RED activation (only if this logic later outgrows YAML).

> Note: window-open **detection** and the **3rd purifier** were moved *into* A during review
> (hardware on hand). Only the window-vs-AC *decisioning* + CO2 remain for B.
