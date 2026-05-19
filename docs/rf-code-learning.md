# RF Code Learning — Broadlink RM4 Pro

`config/template/fans.yaml` is **generated** — edit `scripts/sync_rf_codes.py`, not the YAML directly.

## Setup (once)

```bash
# From ~/dev/HomeAutomationSetup
pyenv local homeautomation
pip install -r scripts/requirements.txt
```

## Learning codes

### 1. Learn all missing codes

```bash
python3 scripts/learn_rf_codes.py
```

Walks through every fan/command, counts down 12s per code, stops as soon as signal received.
Press each remote button once when prompted. Codes saved to `scripts/rf_codes_cache.json` after each press — safe to interrupt and resume.

**Flags:**
```bash
python3 scripts/learn_rf_codes.py --fan fan_yossis_office   # one fan only
python3 scripts/learn_rf_codes.py --relearn                 # overwrite existing codes
python3 scripts/learn_rf_codes.py --freq 315                # 315MHz instead of 433.92
```

#### Type A fans (4 fans × 10 commands)
Devices: `fan_yossis_office`, `fan_danas_office`, `fan_master_bedroom`, `fan_mamad`

| Command | Button |
|---------|--------|
| `fan_toggle` | On/Off |
| `speed_1` … `speed_6` | Speed 1–6 |
| `speed_natural_wind` | Natural wind |
| `direction` | Direction/reverse |
| `light_toggle` | Light on/off |

#### Type B fans (2 fans × 14 commands)
Devices: `fan_balcony_left`, `fan_balcony_right`

| Command | Button |
|---------|--------|
| `speed_1` … `speed_5` | Speed 1–5 (also turns on) |
| `speed_natural_wind` | Natural wind |
| `fan_off` | Off |
| `direction` | Direction/reverse |
| `light_warm` | Warm (also turns on) |
| `light_cool` | Cool |
| `light_natural` | Natural |
| `light_off` | Light off |
| `light_brighter` | Brightness up |
| `light_dimmer` | Brightness down |

### 2. Verify codes work

```bash
python3 scripts/verify_rf_codes.py --fan fan_yossis_office          # light toggle x2, 5s apart
python3 scripts/verify_rf_codes.py --fan fan_yossis_office --cmd fan_toggle
python3 scripts/verify_rf_codes.py --fan fan_yossis_office --cmd speed_3 --times 1
```

### 3. Generate fans.yaml + restart HA

Run on blacky:

```bash
python3 scripts/sync_rf_codes.py --cache-only --dry-run   # preview
python3 scripts/sync_rf_codes.py --cache-only --restart   # write + restart HA
```

### 4. Commit the cache

```bash
git add scripts/rf_codes_cache.json
git commit -m "feat: update learned RF codes"
git push
```

---

## Re-learning a specific command

```bash
python3 scripts/learn_rf_codes.py --fan fan_yossis_office --relearn
```

Then re-run step 3.

---

## Troubleshooting

**HA warns about named commands** — commands without learned codes stay as named strings. HA logs a warning but doesn't crash. Learn the missing codes and re-run sync.

**Wrong code / double-press** — re-learn with `--relearn`. Check `verify_rf_codes.py` after.

**RM4 Pro IP changed** — update `DEVICE_IP` in `learn_rf_codes.py` and `verify_rf_codes.py`. Current: `192.168.1.18`.

**Entity IDs after generation:**
- `fan.yossis_office_fan`, `fan.danas_office_fan`, `fan.master_bedroom_fan`, `fan.mamad_fan`
- `fan.balcony_left_fan`, `fan.balcony_right_fan`
- `light.yossis_office_fan_light`, `light.danas_office_fan_light`, etc.
