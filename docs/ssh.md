# SSH, scp, and sync between Mac and blacky

## SSH

```bash
ssh blacky          # ~/.ssh/config alias (key: ~/.ssh/claude_setup_key)
```

Always use the shorthand `ssh blacky` — not `ssh -i ~/.ssh/claude_setup_key yossi@blacky.local`.

## When to use what

| Situation | Command |
|-----------|---------|
| Run a non-interactive command on blacky | `ssh blacky "cd ~/homeassistant && <cmd>"` |
| Interactive script (needs user input / TTY) | Run **locally on Mac** — SSH strips stdin |
| Push gitignored files (cache, generated YAML) | `scp <file> blacky:~/homeassistant/<path>` |
| Push code changes (scripts, config YAML) | `git push` on Mac → `git pull` on blacky |
| Restart a Docker service | `ssh blacky "docker compose -f ~/homeassistant/docker-compose.yml restart <service>"` |

## Repo paths

| Location | Path |
|----------|------|
| Mac | `/Users/yossi_solomon/dev/HomeAutomationSetup/` |
| blacky | `~/homeassistant/` |

## Gitignored files that need manual sync (scp)

- `scripts/rf_codes_cache.json` — RF code cache, learned on Mac
- `config/template/fans.yaml` — generated; sync by running `sync_rf_codes.py --restart` on blacky after pushing cache

## Typical post-learning workflow

```bash
# 1. Learn on Mac (interactive)
~/.pyenv/versions/homeautomation/bin/python3 scripts/learn_rf_codes.py --fan <fan_id>

# 2. Push cache to blacky
scp scripts/rf_codes_cache.json blacky:~/homeassistant/scripts/

# 3. Sync + restart HA on blacky
ssh blacky "cd ~/homeassistant && python3 scripts/sync_rf_codes.py --restart"

# 4. Push code changes (if any scripts were modified)
git push && ssh blacky "cd ~/homeassistant && git pull"
```
