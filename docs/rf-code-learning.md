# RF Code Learning — Broadlink RM4 Pro

`config/template/fans.yaml` is **generated** — edit `scripts/sync_rf_codes.py`, not the YAML directly.

## Setup (once)

```bash
# From ~/dev/HomeAutomationSetup
pyenv local homeautomation
pip install -r scripts/requirements.txt
```

## Learning new codes

### 1. Start broadlinkmanager

```bash
ssh blacky 'cd ~/homeassistant && docker compose --profile learning up broadlinkmanager -d'
```

Open **http://blacky.local:7020** → Devices → Autodiscover → select RM4 Pro (192.168.1.19).

### 2. Learn each code

Go to **Learn** tab → select RF → enter name as `device/command` → point remote at RM4 Pro → press button.

**Naming convention:** `{device_id}/{command}` — e.g. `fan_danas_office/fan_toggle`

#### Type A fans (4 fans × 10 commands)
Devices: `fan_danas_office`, `fan_yossis_office`, `fan_master_bedroom`, `fan_mamad`

| Command | Trigger |
|---------|---------|
| `fan_toggle` | On/Off button |
| `speed_1` … `speed_6` | Speed buttons 1–6 |
| `speed_turbo` | Turbo button |
| `direction` | Direction/reverse button |
| `light_toggle` | Light on/off button |

#### Type B fans (2 fans × 14 commands)
Devices: `fan_balcony_left`, `fan_balcony_right`

| Command | Trigger |
|---------|---------|
| `speed_1` … `speed_5` | Speed buttons (also turns fan on) |
| `speed_turbo` | Turbo button |
| `fan_off` | Off button |
| `direction` | Direction/reverse button |
| `light_warm` | Warm color button (also turns light on) |
| `light_cool` | Cool color button |
| `light_natural` | Natural color button |
| `light_off` | Light off button |
| `light_brighter` | Brightness up button |
| `light_dimmer` | Brightness down button |

### 3. Sync codes → regenerate + deploy fans.yaml

`fans.yaml` is gitignored (generated file). Deploy directly via SCP.

```bash
cd ~/dev/HomeAutomationSetup

# Dry run first — verify output
python scripts/sync_rf_codes.py --dry-run

# Generate + deploy to blacky + restart HA
python scripts/sync_rf_codes.py --deploy --restart
```

Codes accumulate in `scripts/rf_codes_cache.json`. Partial sessions are safe — re-run sync any time.

### 4. Commit the cache

`rf_codes_cache.json` is the source of truth — commit it to git.

```bash
git add scripts/rf_codes_cache.json
git commit -m "feat: update learned RF codes"
git push
```

### 5. Stop broadlinkmanager

```bash
ssh blacky 'cd ~/homeassistant && docker compose --profile learning stop broadlinkmanager'
```

---

## Re-learning a specific command

To re-learn a command that was already synced:

1. Re-learn the command in broadlinkmanager (same `device/command` name — it overwrites)
2. Re-run `python scripts/sync_rf_codes.py --deploy --restart`
3. Commit the updated cache: `git add scripts/rf_codes_cache.json && git commit -m "..."`

The cache stores the latest code per `device/command` key. No manual YAML editing needed.

---

## Troubleshooting

**broadlinkmanager can't find device** — RM4 Pro uses UDP broadcast. Ensure `network_mode: host` is set in docker-compose.yml (it is). If IP changed, check router DHCP table.

**HA warns about named commands** — Commands without learned codes stay as named strings (e.g. `"fan_toggle"`). HA logs a warning but doesn't crash. Learn the missing codes and re-sync.

**Entity IDs after generation** — Entity IDs are derived from the `name` field:
- `fan.danas_office_fan`, `fan.yossis_office_fan`, `fan.master_bedroom_fan`, `fan.mamad_fan`
- `fan.balcony_left_fan`, `fan.balcony_right_fan`
- `light.danas_office_fan_light`, `light.yossis_office_fan_light`, etc.
