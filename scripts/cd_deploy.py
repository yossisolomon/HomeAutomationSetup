"""Safe continuous-deploy poller for blacky (backlog #17).

Runs every ~2 min from cron as `yossi` (who owns config/ since #10 and is in the
`docker` group). Fetches origin/main; if it advanced, pulls, validates with HA
`check_config` in the real container, then APPLIES via change-detection — a graceful
HA API reload for automations/scripts/scenes/templates/blueprints, or a full
container recreate for anything heavier (configuration.yaml, secrets, packages,
custom_components, compose, requirements). On a bad config or an unhealthy restart it
rolls back (`git reset --hard`) and alerts via Telegram. Replaces the manual
`make check`. Design: docs/state-of-world.md §7 #17.

Stdlib only (blacky's system python has no `yaml`). Pure functions (change
classification, secret parsing) + a thin imperative main().

Exit codes: 0 ok/no-op; 2 pull failed; 4 check_config failed (rolled back);
5 unhealthy after apply (rolled back).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


# ── Change classification (pure) ─────────────────────────────────────────────
# Files HA can hot-reload via a service call (no restart):
RELOAD_EXACT = {
    "config/automations.yaml": ["automation/reload"],
    "config/scripts.yaml": ["script/reload"],
    "config/scenes.yaml": ["scene/reload"],
}
RELOAD_PREFIX = {
    "config/template/": ["template/reload"],
    # Blueprints are consumed by automations + scripts; reload both so the
    # consuming entities pick up the new blueprint.
    "config/blueprints/": ["automation/reload", "script/reload"],
}


def is_reload_safe(path: str) -> bool:
    """True if a changed `path` can be applied by an HA reload service call alone."""
    return path in RELOAD_EXACT or any(path.startswith(p) for p in RELOAD_PREFIX)


def reload_services_for(path: str) -> list:
    """The reload service(s) ('domain/service') a reload-safe `path` requires."""
    if path in RELOAD_EXACT:
        return RELOAD_EXACT[path]
    for prefix, services in RELOAD_PREFIX.items():
        if path.startswith(prefix):
            return services
    return []


def is_ha_relevant(path: str) -> bool:
    """True if a changed `path` affects the running HA instance (so it needs applying).

    Docs/markdown, and other services' files (grafana/, prometheus/, scripts/, …) are
    NOT HA-relevant — they get pulled but this poller takes no HA action for them.
    """
    if path.endswith(".md"):
        return False
    return (
        path.startswith("config/")
        or path == "docker-compose.yml"
        or path == "hacs-manifest.yaml"
        or os.path.basename(path).startswith("requirements")
    )


def classify_changes(paths) -> dict:
    """Decide how to apply a set of changed file paths (relative to repo root).

    Returns {"action": "none"|"reload"|"restart", "reload_services": [sorted]}.
    - none    → no HA-relevant file changed; nothing to apply.
    - reload  → every HA-relevant change is reload-safe; call the listed services.
    - restart → at least one change needs a full container recreate (superset-safe:
                mixed reload+restart sets always restart).
    Pure: no I/O.
    """
    ha = [p for p in paths if is_ha_relevant(p)]
    if not ha:
        return {"action": "none", "reload_services": []}
    if all(is_reload_safe(p) for p in ha):
        services = sorted({s for p in ha for s in reload_services_for(p)})
        return {"action": "reload", "reload_services": services}
    return {"action": "restart", "reload_services": []}


def parse_secret(text: str, key: str) -> str | None:
    """Read `key` from a flat HA secrets.yaml without a YAML parser (blacky has none).

    Strips one pair of surrounding quotes — HA secrets are often written quoted, and a
    quote-wrapped bearer token silently fails auth (learned the hard way on #18).
    """
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        k, v = s.split(":", 1)
        if k.strip() == key:
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v
    return None


# ── Imperative helpers (thin; monkeypatched in tests) ────────────────────────
def _log(msg: str) -> None:
    print(msg)
    subprocess.run(["logger", "-t", "cd-deploy", msg], check=False)


def git(args, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def rev(cwd: str, ref: str) -> str:
    return git(["rev-parse", ref], cwd).stdout.strip()


def changed_files(cwd: str, old: str, new: str) -> list:
    out = git(["diff", "--name-only", f"{old}..{new}"], cwd).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def check_config(container: str) -> int:
    """Run HA's config validator inside the real container. 0 = valid."""
    return subprocess.run(
        ["docker", "exec", container, "python", "-m", "homeassistant",
         "--script", "check_config", "-c", "/config"]
    ).returncode


def reload_via_api(base_url: str, token: str, service: str, timeout: int = 30) -> int:
    """POST /api/services/<domain>/<service>. Returns the HTTP status (0 on transport error)."""
    domain, _, name = service.partition("/")
    req = urllib.request.Request(
        f"{base_url}/api/services/{domain}/{name}",
        data=b"{}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0


def restart_container(ha_dir: str, container: str) -> int:
    """Recreate the container (applies compose changes AND reloads config). Brief HA downtime."""
    return subprocess.run(
        ["docker", "compose", "up", "-d", "--force-recreate", container], cwd=ha_dir
    ).returncode


def ha_healthy(base_url: str, timeout: int = 5) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/", timeout=timeout) as r:
            return r.status < 400
    except urllib.error.HTTPError as e:
        return e.code < 400
    except (urllib.error.URLError, OSError):
        return False


def wait_healthy(base_url: str, timeout: int = 150, interval: int = 10) -> bool:
    waited = 0
    while waited < timeout:
        time.sleep(interval)
        waited += interval
        if ha_healthy(base_url):
            return True
    return False


def send_telegram(token: str | None, chat: str | None, text: str) -> None:
    """Fire-and-forget Telegram alert via the Bot API (runs on blacky; never the Mac)."""
    if not token or not chat:
        _log("telegram: no token/chat in secrets — skipping alert")
        return
    data = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:  # noqa: BLE001 - alerting must never crash the deploy
        _log(f"telegram send failed: {e}")


def _read_secrets(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Safe CD poller for blacky (backlog #17).")
    p.add_argument("--ha-dir", default="/home/yossi/homeassistant", help="repo + compose dir on blacky")
    p.add_argument("--branch", default="main")
    p.add_argument("--container", default="homeassistant")
    p.add_argument("--base-url", default="http://localhost:8123", help="HA base URL for reload/health")
    p.add_argument("--secrets", default=None, help="secrets.yaml path (default <ha-dir>/config/secrets.yaml)")
    p.add_argument("--lock", default="/tmp/cd_deploy.lock")
    p.add_argument("--health-timeout", type=int, default=150)
    p.add_argument("--dry-run", action="store_true", help="fetch + classify only; apply nothing")
    args = p.parse_args(argv)

    secrets_path = args.secrets or os.path.join(args.ha_dir, "config", "secrets.yaml")
    secrets = _read_secrets(secrets_path)
    tg_token = parse_secret(secrets, "telegram_bot_token")
    tg_chat = parse_secret(secrets, "telegram_chat_id")
    cd_token = parse_secret(secrets, "cd_deploy_token")

    def alert(text: str) -> None:
        _log(text)
        send_telegram(tg_token, tg_chat, text)

    # Single-instance guard: a slow deploy must not overlap the next 2-min tick.
    import fcntl
    lock_fh = open(args.lock, "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _log("another cd_deploy run holds the lock — skipping this tick")
        return 0

    if git(["fetch", "origin", args.branch], args.ha_dir).returncode != 0:
        _log("git fetch failed — skipping")
        return 0
    prev = rev(args.ha_dir, "HEAD")
    target = rev(args.ha_dir, f"origin/{args.branch}")
    if not target or prev == target:
        _log(f"up to date at {prev[:8]} — no-op")
        return 0

    _log(f"new commits {prev[:8]}..{target[:8]} — deploying")
    files = changed_files(args.ha_dir, prev, target)
    plan = classify_changes(files)

    if args.dry_run:
        _log(f"DRY-RUN: action={plan['action']} services={plan['reload_services']} files={files}")
        return 0

    if git(["pull", "--ff-only", "origin", args.branch], args.ha_dir).returncode != 0:
        alert(f"CD: git pull --ff-only failed at {target[:8]} — not deploying. Check blacky tree.")
        return 2

    if check_config(args.container) != 0:
        git(["reset", "--hard", prev], args.ha_dir)
        alert(f"CD: check_config FAILED for {target[:8]} — rolled back to {prev[:8]}.")
        return 4

    action = plan["action"]
    if action == "none":
        _log(f"deployed {target[:8]}: no HA-relevant changes (no reload/restart needed)")
        return 0

    # Reload path needs the admin CD token; without it, fall back to a restart.
    if action == "reload" and not cd_token:
        _log("no cd_deploy_token in secrets — escalating reload to restart")
        action = "restart"

    if action == "reload":
        failed = [s for s in plan["reload_services"]
                  if reload_via_api(args.base_url, cd_token, s) != 200]
        if failed:
            _log(f"reload calls failed {failed} — escalating to restart")
            action = "restart"
        else:
            alert(f"CD: deployed {target[:8]} via reload ({', '.join(plan['reload_services'])}).")
            return 0

    # restart (full recreate) + post-apply health gate + rollback on failure.
    restart_container(args.ha_dir, args.container)
    if not wait_healthy(args.base_url, timeout=args.health_timeout):
        git(["reset", "--hard", prev], args.ha_dir)
        restart_container(args.ha_dir, args.container)
        alert(f"CD: {target[:8]} unhealthy after restart — rolled back to {prev[:8]} + restarted.")
        return 5

    alert(f"CD: deployed {target[:8]} via restart ({len(files)} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
