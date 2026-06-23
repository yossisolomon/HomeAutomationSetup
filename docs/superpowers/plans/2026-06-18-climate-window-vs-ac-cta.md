# Window-vs-A/C CTA + CO2/Ventilation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When apartment air degrades (high CO2 or PM), send a Telegram call-to-action that
recommends opening a window vs running the central A/C — decided by live outdoor AQI + temp — and
acts on the button press.

**Architecture:** Whole-apartment single unit (one central A/C, no per-room lever). New template
`binary_sensor`s in `config/template/climate_cta.yaml` derive the signals; helpers hold tunables +
a kill switch + a cooldown timer; one blueprint-instance script (`script.climate_cta`) sends the
CTA; one `mode=cta` automation triggers it under guards. Mirrors Part A's
`config/template/purifier_auto.yaml` + helper + meta'd-automation pattern. Reuses Part A's global
`binary_sensor.any_window_open`.

**Tech Stack:** Home Assistant YAML (template integration, input_boolean/number/datetime, timer),
the `telegram_confirmable` script blueprint, yamllint + the ToC pre-commit hook.

**Spec:** `docs/superpowers/specs/2026-06-18-climate-window-vs-ac-cta-design.md`

**Validation note:** This is pure HA config — there is no pytest unit layer for it. The
verification gates are `make lint` (yamllint, local), the ToC `--check` (meta present + unique
alias — pre-commit hook + CI), and `make check` (full HA `check_config`, runs in the container on
blacky). "Run the test" steps below map to these gates.

**Live-resolve token:** `sensor.waqi_REPLACE_ME` is the WAQI station sensor (state = AQI;
`temperature` attribute = outdoor °C). Its real id is resolved on blacky in Task 8. Until then the
templates **fail safe**: a missing/unknown WAQI value yields "outside not OK" → the CTA recommends
the A/C and never suggests opening a window onto unknown outdoor air.

---

### Task 1: Helpers — kill switch, tunables, quiet-hours, cooldown timer

**Files:**
- Modify: `config/input_boolean.yaml`
- Create: `config/input_number.yaml`
- Modify: `config/input_datetime.yaml`
- Create: `config/timer.yaml`
- Modify: `config/configuration.yaml`

- [ ] **Step 1: Append the kill switch to `config/input_boolean.yaml`**

Append (the existing file has no trailing-blank convention issues — add one blank line then):

```yaml

# Climate window-vs-A/C CTA master switch. No `initial:` (persists last state, comes up OFF
# on first load) — same safe bring-up as purifier_auto_enable.
climate_cta_enable:
  name: Climate CTA Enable
  icon: mdi:message-alert
```

- [ ] **Step 2: Create `config/input_number.yaml`**

```yaml
# Tunables for the climate window-vs-A/C CTA. `initial:` sets a sane default but resets on
# every HA restart (restarts are rare; deploys are reload-safe) — matches input_datetime's
# choice. Tune from the HA dashboard, NOT by replying to the Telegram message.
ac_cool_setpoint:
  name: A/C Cool Setpoint
  icon: mdi:thermometer
  min: 16
  max: 30
  step: 1
  unit_of_measurement: "°C"
  initial: 24

outdoor_aqi_ventilate_max:
  name: Outdoor AQI Ventilate Max
  icon: mdi:air-filter
  min: 0
  max: 300
  step: 5
  initial: 100

ventilate_max_outdoor_temp:
  name: Ventilate Max Outdoor Temp
  icon: mdi:thermometer
  min: 10
  max: 40
  step: 1
  unit_of_measurement: "°C"
  initial: 26
```

- [ ] **Step 3: Append the quiet-hours pair to `config/input_datetime.yaml`**

```yaml

climate_cta_quiet_start:
  name: Climate CTA Quiet Start
  has_date: false
  has_time: true
  initial: "22:00:00"

climate_cta_quiet_end:
  name: Climate CTA Quiet End
  has_date: false
  has_time: true
  initial: "08:00:00"
```

- [ ] **Step 4: Create `config/timer.yaml`**

```yaml
# Re-prompt rate-limit for the climate CTA: the automation only fires when this is idle,
# then starts it. 2h between prompts.
climate_cta_cooldown:
  name: Climate CTA Cooldown
  duration: "02:00:00"
```

- [ ] **Step 5: Wire the two new includes into `config/configuration.yaml`**

Replace the block:

```yaml
input_boolean: !include input_boolean.yaml
input_datetime: !include input_datetime.yaml
```

with:

```yaml
input_boolean: !include input_boolean.yaml
input_datetime: !include input_datetime.yaml
input_number: !include input_number.yaml
timer: !include timer.yaml
```

- [ ] **Step 6: Lint**

Run: `make lint`
Expected: PASS (no yamllint errors).

- [ ] **Step 7: Commit**

```bash
git add config/input_boolean.yaml config/input_number.yaml config/input_datetime.yaml config/timer.yaml config/configuration.yaml
git commit -m "feat(climate-cta): add helpers — kill switch, tunables, quiet-hours, cooldown"
```

---

### Task 2: Template signals — `config/template/climate_cta.yaml`

**Files:**
- Create: `config/template/climate_cta.yaml`

- [ ] **Step 1: Create the file**

```yaml
# Window-vs-A/C CTA + CO2/ventilation — derived signals.
# Consumed by the climate-cta-ventilate automation + script.climate_cta. See
# docs/superpowers/specs/2026-06-18-climate-window-vs-ac-cta-design.md
#
# Same this.state hysteresis caveat as purifier_auto.yaml: the hysteresis memory does NOT
# survive an HA restart (this.state -> 'unknown' re-evaluates against the ON thresholds;
# fails safe). The WAQI sensor id is resolved live on blacky — until then a missing value
# makes outdoor_air_ok false, so the CTA recommends the A/C (never a window onto unknown air).

- binary_sensor:
    - name: "Apartment CO2 High"
      unique_id: apartment_co2_high
      device_class: problem
      state: >
        {% set ids = ['sensor.airmonitor2_co2',
                      'sensor.airmonitorlitemaster_co2',
                      'sensor.mamadairmonitor_co2'] %}
        {% set vals = ids | map('states')
                          | reject('in', ['unavailable', 'unknown', 'none'])
                          | map('float', 0) | list %}
        {% if vals | length == 0 %}
          false
        {% elif this.state == 'on' %}
          {{ vals | max > 1000 }}
        {% else %}
          {{ vals | max >= 1400 }}
        {% endif %}

    - name: "Apartment Air Degraded"
      unique_id: apartment_air_degraded
      device_class: problem
      state: >
        {{ is_state('binary_sensor.apartment_co2_high', 'on')
           or is_state('binary_sensor.living_air_bad', 'on')
           or is_state('binary_sensor.master_air_bad', 'on')
           or is_state('binary_sensor.mamad_air_bad', 'on') }}

    - name: "Outdoor Air Ok"
      unique_id: outdoor_air_ok
      state: >
        {% set aqi = states('sensor.waqi_REPLACE_ME') | float(-1) %}
        {% set maxaqi = states('input_number.outdoor_aqi_ventilate_max') | float(100) %}
        {{ aqi >= 0 and aqi <= maxaqi }}

    - name: "Ventilate Favorable"
      unique_id: ventilate_favorable
      state: >
        {% set otemp = state_attr('sensor.waqi_REPLACE_ME', 'temperature') | float(99) %}
        {% set tmax = states('input_number.ventilate_max_outdoor_temp') | float(26) %}
        {{ is_state('binary_sensor.outdoor_air_ok', 'on')
           and otemp <= tmax
           and is_state('binary_sensor.any_window_open', 'off') }}

    - name: "CTA Quiet Hours"
      unique_id: cta_quiet_hours
      state: >
        {% set now_s = now().hour * 3600 + now().minute * 60 + now().second %}
        {% set start = state_attr('input_datetime.climate_cta_quiet_start', 'timestamp')|int(0) %}
        {% set end = state_attr('input_datetime.climate_cta_quiet_end', 'timestamp')|int(0) %}
        {% if start <= end %}
          {{ start <= now_s < end }}
        {% else %}
          {{ now_s >= start or now_s < end }}
        {% endif %}
```

- [ ] **Step 2: Lint**

Run: `make lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add config/template/climate_cta.yaml
git commit -m "feat(climate-cta): add derived template signals (CO2/degraded/outdoor-ok/ventilate/quiet)"
```

---

### Task 3: CTA script — `config/scripts.yaml`

**Files:**
- Modify: `config/scripts.yaml` (currently empty)

- [ ] **Step 1: Write the script (blueprint instance). The `# meta:` comment is REQUIRED — the ToC `--check` validates scripts too.**

```yaml
# meta: intent="Telegram CTA: choose open-window vs run central A/C on degraded air"; waf=med; mode=cta
climate_cta:
  alias: climate-cta-window-vs-ac
  use_blueprint:
    path: homeassistant/telegram_confirmable.yaml
    input:
      target_chat: !secret telegram_chat_id
      message: >-
        {% set fav = is_state('binary_sensor.ventilate_favorable', 'on') %}
        {% set aqi = states('sensor.waqi_REPLACE_ME') %}
        {% set otemp = state_attr('sensor.waqi_REPLACE_ME', 'temperature') %}
        {% set co2 = [states('sensor.airmonitor2_co2') | float(0),
                      states('sensor.airmonitorlitemaster_co2') | float(0),
                      states('sensor.mamadairmonitor_co2') | float(0)] | max %}
        🏠 Indoor air degrading (CO2 {{ co2 | round }} ppm).
        Outside: AQI {{ aqi }}, {{ otemp }}°C.
        {% if fav %}👉 Better option: open a window (clean, cool outside).{% else %}👉 Better option: run the A/C (outside not good for ventilating).{% endif %}
      confirm_text: "❄️ Run A/C"
      confirm_action:
        - action: climate.set_hvac_mode
          target:
            entity_id: climate.smartir_climate_1581
          data:
            hvac_mode: cool
        - action: climate.set_temperature
          target:
            entity_id: climate.smartir_climate_1581
          data:
            temperature: "{{ states('input_number.ac_cool_setpoint') | float(24) }}"
      dismiss_text: "🪟 Open window"
      dismiss_action:
        - action: telegram_bot.send_message
          data:
            target: !secret telegram_chat_id
            message: "👍 Opening a window — A/C standing down."
        - if:
            - condition: not
              conditions:
                - condition: state
                  entity_id: climate.smartir_climate_1581
                  state: "off"
          then:
            - action: climate.turn_off
              target:
                entity_id: climate.smartir_climate_1581
```

- [ ] **Step 2: Lint + ToC check**

Run: `make lint && python scripts/gen_automations_toc.py --check`
Expected: PASS (script has meta + unique name).

- [ ] **Step 3: Commit**

```bash
git add config/scripts.yaml
git commit -m "feat(climate-cta): add window-vs-AC Telegram CTA script (blueprint instance)"
```

---

### Task 4: Automation — `config/automations.yaml`

**Files:**
- Modify: `config/automations.yaml` (append; the file ends WITHOUT a trailing newline — add one before appending)

- [ ] **Step 1: Append the automation (note the required `# meta:` line)**

```yaml
# meta: intent="when apartment air degrades (CO2/PM), ask via Telegram to open a window vs run the central A/C, decided by outdoor AQI + temp"; waf=med; mode=cta
- alias: climate-cta-ventilate
  id: climate_cta_ventilate
  mode: single
  triggers:
    - trigger: state
      entity_id: binary_sensor.apartment_air_degraded
      to: "on"
  conditions:
    - condition: state
      entity_id: input_boolean.climate_cta_enable
      state: "on"
    - condition: state
      entity_id: binary_sensor.cta_quiet_hours
      state: "off"
    - condition: state
      entity_id: timer.climate_cta_cooldown
      state: idle
  actions:
    - action: script.climate_cta
    - action: timer.start
      target:
        entity_id: timer.climate_cta_cooldown
```

- [ ] **Step 2: Regenerate the ToC + verify it's the only diff, and meta validates**

Run: `python scripts/gen_automations_toc.py --check && python scripts/gen_automations_toc.py && git status --short`
Expected: `--check` exits 0; `docs/automations.md` shows the two new rows (climate-cta-ventilate automation + climate-cta-window-vs-ac script).

- [ ] **Step 3: Lint**

Run: `make lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add config/automations.yaml docs/automations.md
git commit -m "feat(climate-cta): wire degraded-air trigger automation + regenerate ToC"
```

---

### Task 5: State-of-world doc

**Files:**
- Modify: `docs/state-of-world.md` (backlog item #1)

- [ ] **Step 1: Update backlog #1's Part B line** from `*Part B (open):* window-vs-AC call-to-action on outdoor AQ + CO2/ventilation.` to mark it done and point at the new spec/plan:

```markdown
   *Part B done:* whole-apartment window-vs-AC Telegram CTA on outdoor AQI + temp, plus
   CO2/ventilation prompt. HA-YAML — `template/climate_cta.yaml` + `climate_cta` blueprint
   script + `climate-cta-ventilate` automation + helpers (kill switch, tunables, quiet-hours,
   cooldown). Spec/plan: `docs/superpowers/{specs,plans}/2026-06-18-climate-window-vs-ac-cta*`.
   Go-live (resolve WAQI sensor id, verify A/C controls, prove the Telegram button flow,
   flip `climate_cta_enable` on) tracked in the plan's live tasks.
```

- [ ] **Step 2: Commit**

```bash
git add docs/state-of-world.md
git commit -m "docs(state-of-world): mark backlog #1 Part B done"
```

---

### Task 6: PR

- [ ] **Step 1: Push + open the PR**

```bash
git push -u origin climate-window-vs-ac-cta
gh pr create --title "feat(climate): window-vs-A/C CTA + CO2/ventilation (backlog #1 Part B)" \
  --body "Implements backlog #1 Part B. Whole-apartment Telegram CTA: degraded air (CO2 >=1400 or PM) -> recommend open-window vs run central A/C, decided by live WAQI AQI + outdoor temp; acts on the button press. Spec/plan under docs/superpowers/. CTA scripts/templates/automations are reload-safe.

NOTE before go-live: resolve sensor.waqi_REPLACE_ME on blacky, verify climate.smartir_climate_1581 controls, prove the Telegram inline-button callback (blueprint's first real consumer), then flip input_boolean.climate_cta_enable on."
```

- [ ] **Step 2: Watch CI to green**

Run: `gh pr checks --watch`
Expected: lint / toc / pytest / normalizer all pass.

---

### Task 7: Squash-merge

- [ ] **Step 1: After CI is green and review approves, squash-merge**

```bash
gh pr merge --squash
```

blacky's CD poller auto-deploys; `template/**` + automations/scripts are reload-safe (no restart).

---

### Task 8: Live go-live on blacky (manual, after merge + deploy)

These need the live system and Yossi's hands on the hardware — do interactively, not in CI.

- [ ] **Step 1: Resolve the WAQI sensor id.** On blacky, find the real entity id (state = AQI,
  has a `temperature` attribute):

```bash
ssh blacky 'docker exec homeassistant grep -o "sensor.waqi[a-z0-9_]*" /config/.storage/core.entity_registry | sort -u'
```

Replace both `sensor.waqi_REPLACE_ME` occurrences (in `config/template/climate_cta.yaml` and
`config/scripts.yaml`) with the resolved id via a follow-up commit + PR. Confirm in Dev Tools →
Template that `states('<id>')` returns the AQI and `state_attr('<id>', 'temperature')` returns °C.

- [ ] **Step 2: Verify the A/C controls** on `climate.smartir_climate_1581` (Dev Tools → Actions):
  `climate.set_hvac_mode` cool, `climate.set_temperature`, `climate.turn_off` — each physically
  confirmed on the unit.

- [ ] **Step 3: Prove the Telegram button flow** (blueprint's first real consumer): with
  `input_boolean.climate_cta_enable` on, run `script.climate_cta` manually → both inline buttons
  render; tap **Run A/C** → A/C goes cool @ setpoint; re-run, tap **Open window** → ack message +
  A/C turns off. Confirm each tap emits a `telegram_callback` (Dev Tools → Events).

- [ ] **Step 4: Exercise the decision + guards** (Dev Tools state overrides):
  - Force a CO2 sensor ≥ 1400 → `apartment_co2_high` + `apartment_air_degraded` flip on → CTA fires.
  - Set `input_number.outdoor_aqi_ventilate_max` low (e.g. 10) vs high (e.g. 300) → message
    recommendation flips A/C ↔ window. Same for `ventilate_max_outdoor_temp`.
  - Confirm the cooldown timer blocks a second prompt within 2h, and a quiet-hours window
    (set start/end around now) suppresses the CTA entirely.

- [ ] **Step 5: Leave `climate_cta_enable` ON** to arm the feature.
