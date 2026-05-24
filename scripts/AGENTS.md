# scripts/ — RF Remote Learning

## Scripts

| Script | Purpose |
|--------|---------|
| `learn_rf_codes.py` | Learn RF codes from Broadlink RM4 Pro → `rf_codes_cache.json` |
| `verify_rf_codes.py` | Send a learned code to verify the device responds |
| `sync_rf_codes.py` | Regenerate `config/template/fans.yaml` from cache + restart HA |

Fan/command definitions: `fans.json`.  
Cache: `rf_codes_cache.json` — accumulates across runs, safe to interrupt/resume. **Gitignored** — sync via `scp`, not git (see `docs/ssh.md`).

---

## Python environment

| Location | How |
|----------|-----|
| **Mac** | pyenv venv `homeautomation` (Python 3.11.4). Auto-activates via `.python-version`. If pyenv not on PATH: `~/.pyenv/versions/homeautomation/bin/python3` |
| **blacky** | `broadlink` installed at system `python3` — no venv needed |

---

## Where to run each script

| Script | Run on | Why |
|--------|--------|-----|
| `learn_rf_codes.py` | **Mac** | Needs interactive TTY for button prompts. SSH strips stdin → EOFError |
| `verify_rf_codes.py` | Mac | Same LAN as Broadlink, no TTY needed |
| `sync_rf_codes.py --restart` | **blacky** | Docker runs there; `docker compose restart` won't work from Mac |

---

## Common commands

```bash
# Learn all missing commands for one fan (Mac)
~/.pyenv/versions/homeautomation/bin/python3 scripts/learn_rf_codes.py --fan fan_mamad

# Re-learn one specific command (Mac)
~/.pyenv/versions/homeautomation/bin/python3 scripts/learn_rf_codes.py --fan fan_mamad --cmd fan_toggle

# Verify a code fires — send once (Mac)
~/.pyenv/versions/homeautomation/bin/python3 scripts/verify_rf_codes.py --fan fan_mamad --cmd light_toggle --times 1

# After learning: push cache to blacky, then sync + restart HA
scp scripts/rf_codes_cache.json blacky:~/homeassistant/scripts/
ssh blacky "cd ~/homeassistant && python3 scripts/sync_rf_codes.py --restart"
```

---

## Validation — 250B rule

All valid RF codes = **250 bytes** after base64 decode. The learn script auto-rejects non-250B captures. Check cache:

```bash
~/.pyenv/versions/homeautomation/bin/python3 -c "
import json, base64
cache = json.load(open('scripts/rf_codes_cache.json'))
bad = {k: len(base64.b64decode(v)) for k, v in cache.items() if len(base64.b64decode(v)) != 250}
print(bad or 'All 250B')
"
```

---

## Fan IDs and types

See `fans.json` for full list. Types:

| Type | Fans | Commands |
|------|------|----------|
| A | `fan_yossis_office`, `fan_danas_office`, `fan_master_bedroom`, `fan_mamad` | `fan_toggle`, `speed_1`–`speed_6`, `speed_natural_wind`, `direction`, `light_toggle` |
| B | `fan_balcony_left`, `fan_balcony_right` | `speed_1`–`speed_5`, `speed_natural_wind`, `fan_off`, `direction`, `light_warm/cool/natural/off`, `light_brighter/dimmer` |
