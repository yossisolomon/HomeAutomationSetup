# NAS Snapshot Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace blacky's three ad-hoc mirror crons with one versioned script that takes GFS-tiered, hardlink-dedup'd point-in-time snapshots of the durable Home Assistant state to the NAS.

**Architecture:** A stdlib-only Python module `scripts/backup_to_nas.py` — pure, unit-tested functions (exclude-loading, GFS retention math, snapshot discovery) wrapped by a thin imperative `main()` that mount-guards, rsyncs into an atomic `.partial`, promotes to weekly/monthly tiers via recursive hardlink, prunes per-tier by count, and logs. A tracked `scripts/backup-exclude.txt` drives rsync excludes. `setup.sh` installs a single root cron via a `/etc/cron.d/nas-snapshot` drop-in (folds the un-versioned-crons gap). Snapshots are plain browsable dirs; restore = `cp`.

**Tech Stack:** Python 3.10+ (stdlib only — `argparse`, `subprocess`, `pathlib`, `datetime`, `shutil`, `os`), `rsync --link-dest`, `cp -al`, pytest. Mirrors the existing `scripts/gen_hacs_manifest.py` + `tests/test_gen_hacs_manifest.py` pattern.

---

## File Structure

- **Create `scripts/backup_to_nas.py`** — the whole feature. Pure functions:
  `load_excludes`, `plan_retention`, `tier_names`, `latest_snapshot`, `is_mountpoint`;
  thin shells: `run_rsync`, `promote`, `prune_dirs`, `main`.
- **Create `scripts/backup-exclude.txt`** — rsync exclude patterns (tracked data file).
- **Create `tests/test_backup_to_nas.py`** — pytest, imports `from scripts import backup_to_nas as b`.
- **Modify `setup.sh`** — add a numbered section that writes `/etc/cron.d/nas-snapshot`.
- **Modify `docs/state-of-world.md`** — mark backlog #14 done; add #15 (delete superseded mirrors).

Everything runs on blacky out of the repo checkout at `/home/yossi/homeassistant/`, so there is no separate deploy step. The repo dir on the Mac is `/Users/yossi_solomon/dev/HomeAutomationSetup`; all commands below run there unless they say "on blacky".

**Module API contract (referenced across tasks — define exactly these names/signatures):**

```python
def load_excludes(path: str) -> list[str]: ...
def tier_names(today: datetime.date) -> dict[str, str]:
    # -> {"daily": "2026-06-11", "weekly": "2026-W24", "monthly": "2026-06"}
def plan_retention(existing: dict[str, list[str]], today: datetime.date,
                   weekly_day: int = 0, caps: tuple[int, int, int] = (7, 4, 12)) -> dict: ...
def latest_snapshot(dest: str) -> str | None: ...        # absolute path to newest daily, or None
def is_mountpoint(path: str) -> bool: ...                # wraps os.path.ismount
def run_rsync(root: str, dest_partial: str, link_dest: str | None,
              excludes_file: str) -> int: ...            # returns rsync exit code
def promote(src_dir: str, dest_dir: str) -> None: ...    # recursive hardlink (cp -al)
def prune_dirs(paths: list[str]) -> None: ...            # shutil.rmtree each
def main(argv=None) -> int: ...
```

---

### Task 1: Exclude file + `load_excludes`

**Files:**
- Create: `scripts/backup-exclude.txt`
- Create: `scripts/backup_to_nas.py`
- Test: `tests/test_backup_to_nas.py`

- [ ] **Step 1: Create the exclude data file**

Create `scripts/backup-exclude.txt` with exactly:

```
# rsync exclude patterns for backup_to_nas.py — paths relative to the backup root.
# Big transient live-writers: torn-read risk + bulk; recorder DB is in HA native backups.
prometheus/data/
config/home-assistant_v2.db
config/home-assistant_v2.db-shm
config/home-assistant_v2.db-wal
*.log
.git/
**/node_modules/
**/__pycache__/
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_backup_to_nas.py`:

```python
import datetime
import os

import pytest
from scripts import backup_to_nas as b


def test_load_excludes_strips_comments_and_blanks(tmp_path):
    f = tmp_path / "ex.txt"
    f.write_text(
        "# a comment\n"
        "prometheus/data/\n"
        "\n"
        "   # indented comment\n"
        "*.log\n"
        "  config/home-assistant_v2.db  \n",
        encoding="utf-8",
    )
    assert b.load_excludes(str(f)) == [
        "prometheus/data/",
        "*.log",
        "config/home-assistant_v2.db",
    ]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backup_to_nas'` (or `AttributeError`).

- [ ] **Step 4: Write minimal implementation**

Create `scripts/backup_to_nas.py`:

```python
"""Take GFS-tiered, hardlink-dedup'd snapshots of blacky's durable HA state to the NAS.

Runs as root from cron (reads dirs owned by nobody/root/container UIDs). Pure
functions (retention math, exclude loading, snapshot discovery) + a thin imperative
main(). Stdlib only. See docs/superpowers/specs/2026-06-11-nas-snapshot-retention-design.md.
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys


def load_excludes(path: str) -> list[str]:
    """Return rsync exclude patterns from a file, ignoring comments and blank lines."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s)
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add scripts/backup-exclude.txt scripts/backup_to_nas.py tests/test_backup_to_nas.py
git commit -m "feat(backup): exclude file + load_excludes"
```

---

### Task 2: `tier_names` + `plan_retention` (GFS core)

**Files:**
- Modify: `scripts/backup_to_nas.py`
- Test: `tests/test_backup_to_nas.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backup_to_nas.py`:

```python
def test_tier_names():
    d = datetime.date(2026, 6, 11)  # a Thursday, ISO week 24
    assert b.tier_names(d) == {
        "daily": "2026-06-11",
        "weekly": "2026-W24",
        "monthly": "2026-06",
    }


def test_plan_retention_daily_keeps_newest_seven():
    existing = {"daily": [f"2026-06-{n:02d}" for n in range(3, 10)],  # 03..09 = 7
                "weekly": [], "monthly": []}
    today = datetime.date(2026, 6, 10)  # Wed -> no weekly/monthly promotion
    plan = b.plan_retention(existing, today)
    # 7 existing + today (10) = 8 dailies -> prune the oldest (03)
    assert plan["prune"]["daily"] == ["2026-06-03"]
    assert plan["prune"]["weekly"] == []
    assert plan["prune"]["monthly"] == []
    assert plan["promote_weekly"] is False
    assert plan["promote_monthly"] is False
    assert plan["names"]["daily"] == "2026-06-10"


def test_plan_retention_empty_prunes_nothing():
    plan = b.plan_retention({"daily": [], "weekly": [], "monthly": []},
                            datetime.date(2026, 6, 10))
    assert plan["prune"] == {"daily": [], "weekly": [], "monthly": []}


def test_plan_retention_promotes_weekly_on_configured_day():
    today = datetime.date(2026, 6, 8)  # Monday -> weekday 0
    plan = b.plan_retention({"daily": [], "weekly": [], "monthly": []}, today, weekly_day=0)
    assert plan["promote_weekly"] is True
    assert plan["names"]["weekly"] == "2026-W24"


def test_plan_retention_promotes_monthly_on_first():
    today = datetime.date(2026, 6, 1)
    plan = b.plan_retention({"daily": [], "weekly": [], "monthly": []}, today)
    assert plan["promote_monthly"] is True
    assert plan["names"]["monthly"] == "2026-06"


def test_plan_retention_weekly_and_monthly_caps():
    # Use early week names (W01..W04) guaranteed lexically < June's actual ISO week,
    # so we don't depend on June 1's exact week number.
    existing = {
        "daily": [],
        "weekly": [f"2026-W{n:02d}" for n in range(1, 5)],     # 4 existing weeks
        "monthly": [f"2026-{n:02d}" for n in range(1, 13)],    # 12 existing months incl. 2026-06
    }
    today = datetime.date(2026, 6, 1)  # day==1 -> monthly promo
    # force a weekly promo too by matching weekly_day to today's weekday
    plan = b.plan_retention(existing, today, weekly_day=today.weekday())
    # weekly: 4 existing + June's new week = 5 -> prune oldest (W01)
    assert plan["prune"]["weekly"] == ["2026-W01"]
    # monthly: 12 existing + new (2026-06 already in set) -> no growth, no prune
    assert plan["prune"]["monthly"] == []


def test_plan_retention_does_not_duplicate_existing_month():
    existing = {"daily": [], "weekly": [], "monthly": ["2026-06"]}
    today = datetime.date(2026, 6, 1)
    plan = b.plan_retention(existing, today)
    # 2026-06 already present; promotion is idempotent, count stays 1, no prune
    assert plan["prune"]["monthly"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -k "tier_names or plan_retention" -v`
Expected: FAIL — `AttributeError: module 'scripts.backup_to_nas' has no attribute 'tier_names'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/backup_to_nas.py` (after `load_excludes`):

```python
def tier_names(today: datetime.date) -> dict:
    """Map a date to its snapshot directory name in each tier."""
    iso_year, iso_week, _ = today.isocalendar()
    return {
        "daily": today.isoformat(),
        "weekly": f"{iso_year}-W{iso_week:02d}",
        "monthly": f"{today.year}-{today.month:02d}",
    }


def plan_retention(existing: dict, today: datetime.date,
                   weekly_day: int = 0, caps: tuple = (7, 4, 12)) -> dict:
    """Decide promotions and per-tier prunes for a run on `today`.

    `existing` holds the snapshot names already on disk per tier (before this run).
    Today's daily is always created; weekly is promoted when today.weekday()==weekly_day;
    monthly when today.day==1. After folding the new names in, each tier is capped to
    caps=(daily, weekly, monthly), keeping the newest by lexical (=chronological) order.
    Pure: no clock reads, no filesystem access.
    """
    daily_cap, weekly_cap, monthly_cap = caps
    names = tier_names(today)
    promote_weekly = today.weekday() == weekly_day
    promote_monthly = today.day == 1

    def capped_prune(current: list, new: set, cap: int) -> list:
        merged = sorted(set(current) | new)
        return merged[:-cap] if len(merged) > cap else []

    return {
        "names": names,
        "promote_weekly": promote_weekly,
        "promote_monthly": promote_monthly,
        "prune": {
            "daily": capped_prune(existing.get("daily", []), {names["daily"]}, daily_cap),
            "weekly": capped_prune(existing.get("weekly", []),
                                   {names["weekly"]} if promote_weekly else set(), weekly_cap),
            "monthly": capped_prune(existing.get("monthly", []),
                                    {names["monthly"]} if promote_monthly else set(), monthly_cap),
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add scripts/backup_to_nas.py tests/test_backup_to_nas.py
git commit -m "feat(backup): tier_names + GFS plan_retention"
```

---

### Task 3: `latest_snapshot` + `is_mountpoint`

**Files:**
- Modify: `scripts/backup_to_nas.py`
- Test: `tests/test_backup_to_nas.py`

**Note:** `latest_snapshot` returns the newest **daily** snapshot path as the `--link-dest`
anchor. Weekly/monthly snapshots are recursive hardlinks of dailies, so the newest daily
always holds the freshest content and yields full dedup. ISO date names sort lexically =
chronologically, so "newest" is `max()` of the daily dir names. Returns `None` on first
run (no daily yet) → rsync does a full copy.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backup_to_nas.py`:

```python
def test_latest_snapshot_returns_newest_daily(tmp_path):
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / "2026-06-09").mkdir()
    (daily / "2026-06-10").mkdir()
    (daily / "2026-06-08").mkdir()
    assert b.latest_snapshot(str(tmp_path)) == str(daily / "2026-06-10")


def test_latest_snapshot_none_when_empty(tmp_path):
    assert b.latest_snapshot(str(tmp_path)) is None
    (tmp_path / "daily").mkdir()
    assert b.latest_snapshot(str(tmp_path)) is None  # daily dir exists but empty


def test_latest_snapshot_ignores_partial(tmp_path):
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / "2026-06-10").mkdir()
    (daily / "2026-06-11.partial").mkdir()  # in-progress run, must be ignored
    assert b.latest_snapshot(str(tmp_path)) == str(daily / "2026-06-10")


def test_is_mountpoint_delegates(monkeypatch):
    monkeypatch.setattr(b.os.path, "ismount", lambda p: p == "/mnt/nas")
    assert b.is_mountpoint("/mnt/nas") is True
    assert b.is_mountpoint("/tmp/nope") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -k "latest_snapshot or is_mountpoint" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'latest_snapshot'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/backup_to_nas.py`:

```python
def latest_snapshot(dest: str) -> str | None:
    """Absolute path to the newest committed daily snapshot, or None if none exist.

    Ignores `.partial` dirs (in-progress/crashed runs). ISO date names sort
    chronologically, so the newest is the lexical max.
    """
    daily = os.path.join(dest, "daily")
    if not os.path.isdir(daily):
        return None
    names = [n for n in os.listdir(daily)
             if not n.endswith(".partial") and os.path.isdir(os.path.join(daily, n))]
    if not names:
        return None
    return os.path.join(daily, max(names))


def is_mountpoint(path: str) -> bool:
    """True if `path` is a mounted filesystem (guards against writing to an unmounted HDD)."""
    return os.path.ismount(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add scripts/backup_to_nas.py tests/test_backup_to_nas.py
git commit -m "feat(backup): latest_snapshot anchor + mountpoint guard"
```

---

### Task 4: `run_rsync` + `promote` + `prune_dirs`

**Files:**
- Modify: `scripts/backup_to_nas.py`
- Test: `tests/test_backup_to_nas.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backup_to_nas.py`:

```python
def test_run_rsync_builds_expected_argv(monkeypatch):
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        class R:  # noqa: D401 - tiny stub
            returncode = 0
        return R()

    monkeypatch.setattr(b.subprocess, "run", fake_run)
    rc = b.run_rsync("/src", "/dst.partial", "/prev", "/ex.txt")
    assert rc == 0
    argv = captured["argv"]
    assert argv[0] == "rsync"
    assert "-a" in argv and "--delete" in argv
    assert "--link-dest=/prev" in argv
    assert "--exclude-from=/ex.txt" in argv
    assert argv[-2:] == ["/src/", "/dst.partial/"]  # trailing slashes matter


def test_run_rsync_omits_link_dest_when_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(b.subprocess, "run",
                        lambda argv, **kw: captured.update(argv=argv) or type("R", (), {"returncode": 0})())
    b.run_rsync("/src", "/dst.partial", None, "/ex.txt")
    assert not any(a.startswith("--link-dest") for a in captured["argv"])


def test_promote_invokes_cp_al(monkeypatch):
    captured = {}
    monkeypatch.setattr(b.subprocess, "run",
                        lambda argv, **kw: captured.update(argv=argv) or type("R", (), {"returncode": 0})())
    b.promote("/snap/daily/2026-06-10", "/snap/weekly/2026-W24")
    assert captured["argv"] == ["cp", "-al", "/snap/daily/2026-06-10", "/snap/weekly/2026-W24"]


def test_prune_dirs_removes_each(tmp_path):
    d1 = tmp_path / "a"; d1.mkdir(); (d1 / "f").write_text("x")
    d2 = tmp_path / "b"; d2.mkdir()
    b.prune_dirs([str(d1), str(d2)])
    assert not d1.exists() and not d2.exists()


def test_prune_dirs_tolerates_missing(tmp_path):
    b.prune_dirs([str(tmp_path / "ghost")])  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -k "run_rsync or promote or prune_dirs" -v`
Expected: FAIL — missing attributes.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/backup_to_nas.py`:

```python
def run_rsync(root: str, dest_partial: str, link_dest: str | None, excludes_file: str) -> int:
    """rsync `root/` into `dest_partial/` with archive+delete, excludes, and optional
    hardlink dedup against `link_dest`. Returns the rsync exit code."""
    argv = ["rsync", "-a", "--delete", f"--exclude-from={excludes_file}"]
    if link_dest:
        argv.append(f"--link-dest={link_dest}")
    argv += [root.rstrip("/") + "/", dest_partial.rstrip("/") + "/"]
    return subprocess.run(argv).returncode


def promote(src_dir: str, dest_dir: str) -> None:
    """Recursively hardlink `src_dir` into `dest_dir` (cp -al) — no data re-copied."""
    subprocess.run(["cp", "-al", src_dir, dest_dir], check=True)


def prune_dirs(paths: list[str]) -> None:
    """Remove each directory tree; tolerate already-gone paths."""
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add scripts/backup_to_nas.py tests/test_backup_to_nas.py
git commit -m "feat(backup): rsync + recursive-hardlink promote + prune helpers"
```

---

### Task 5: `main()` orchestration + CLI

**Files:**
- Modify: `scripts/backup_to_nas.py`
- Test: `tests/test_backup_to_nas.py`

**Behaviour:** parse args → mount-guard (`return 3` if `--dest`'s mount root not mounted)
→ build paths → rsync into `daily/<date>.partial/` (anchored at `latest_snapshot`) →
treat exit 0/24 as success and `os.replace` to `daily/<date>/`, else log + `return 4`
without promoting/pruning → promote weekly/monthly per `plan_retention` → prune per tier
→ log summary. `--dry-run` prints the plan and returns 0 before any filesystem write.
`--date YYYY-MM-DD` injects "today" (defaults to `datetime.date.today()`).

The mount guard checks the **mount root** of `--dest`, not `--dest` itself: the snapshots
dir lives *under* the mountpoint (`/mnt/nas/snapshots`), so we verify `--mount` (default
`/mnt/nas`) is mounted.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backup_to_nas.py`:

```python
def test_main_aborts_when_not_mounted(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(b, "is_mountpoint", lambda p: False)
    rc = b.main(["--root", str(tmp_path), "--dest", str(tmp_path / "snapshots"),
                 "--mount", "/mnt/nas", "--excludes", str(tmp_path / "ex.txt")])
    assert rc == 3
    assert "not mounted" in capsys.readouterr().err.lower()


def test_main_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(b, "is_mountpoint", lambda p: True)
    ex = tmp_path / "ex.txt"; ex.write_text("*.log\n")
    dest = tmp_path / "snapshots"
    rc = b.main(["--root", str(tmp_path), "--dest", str(dest), "--mount", str(tmp_path),
                 "--excludes", str(ex), "--date", "2026-06-10", "--dry-run"])
    assert rc == 0
    assert not dest.exists()  # nothing created
    assert "DRY-RUN" in capsys.readouterr().out


def test_main_rsync_failure_returns_4_and_skips_prune(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "is_mountpoint", lambda p: True)
    ex = tmp_path / "ex.txt"; ex.write_text("\n")
    pruned = []
    monkeypatch.setattr(b, "run_rsync", lambda *a, **k: 23)  # 23 = partial transfer error
    monkeypatch.setattr(b, "prune_dirs", lambda paths: pruned.extend(paths))
    rc = b.main(["--root", str(tmp_path), "--dest", str(tmp_path / "s"),
                 "--mount", str(tmp_path), "--excludes", str(ex), "--date", "2026-06-10"])
    assert rc == 4
    assert pruned == []  # never prune after a failed copy


def test_main_happy_path_commits_and_promotes(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "is_mountpoint", lambda p: True)
    ex = tmp_path / "ex.txt"; ex.write_text("\n")
    dest = tmp_path / "s"

    def fake_rsync(root, dest_partial, link_dest, excludes_file):
        os.makedirs(dest_partial, exist_ok=True)  # simulate rsync creating the tree
        return 24  # vanished-files, treated as success

    promotes = []
    monkeypatch.setattr(b, "run_rsync", fake_rsync)
    monkeypatch.setattr(b, "promote", lambda s, d: promotes.append((s, d)))
    # 2026-06-01 is a Monday in this scenario? day==1 forces monthly; set weekly_day to match
    rc = b.main(["--root", str(tmp_path), "--dest", str(dest), "--mount", str(tmp_path),
                 "--excludes", str(ex), "--date", "2026-06-01", "--weekly-day", "6"])
    assert rc == 0
    assert (dest / "daily" / "2026-06-01").is_dir()        # .partial committed
    assert not (dest / "daily" / "2026-06-01.partial").exists()
    assert (str(dest / "daily" / "2026-06-01"),
            str(dest / "monthly" / "2026-06")) in promotes  # monthly promo on the 1st
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -k main -v`
Expected: FAIL — `main` does not yet accept these args / lacks the behaviour.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/backup_to_nas.py`:

```python
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _existing_tiers(dest: str) -> dict:
    out = {}
    for tier in ("daily", "weekly", "monthly"):
        d = os.path.join(dest, tier)
        out[tier] = ([n for n in os.listdir(d)
                      if not n.endswith(".partial") and os.path.isdir(os.path.join(d, n))]
                     if os.path.isdir(d) else [])
    return out


def _log(msg: str) -> None:
    print(msg)
    subprocess.run(["logger", "-t", "nas-snapshot", msg], check=False)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="GFS snapshot of HA state to the NAS.")
    p.add_argument("--root", default="/home/yossi/homeassistant", help="backup source root")
    p.add_argument("--dest", default="/mnt/nas/snapshots", help="snapshot tree root")
    p.add_argument("--mount", default="/mnt/nas", help="mountpoint that must be mounted")
    p.add_argument("--excludes",
                   default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "backup-exclude.txt"),
                   help="rsync exclude-from file")
    p.add_argument("--weekly-day", default="mon", help="weekday to promote weekly (mon..sun or 0..6)")
    p.add_argument("--date", default=None, help="override today (YYYY-MM-DD), for testing")
    p.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = p.parse_args(argv)

    today = (datetime.date.fromisoformat(args.date) if args.date
             else datetime.date.today())
    wd = args.weekly_day.lower()
    weekly_day = WEEKDAYS.index(wd) if wd in WEEKDAYS else int(wd)

    if not is_mountpoint(args.mount):
        print(f"{args.mount} not mounted — aborting (refusing to write to local fs).",
              file=sys.stderr)
        return 3

    names = tier_names(today)
    plan = plan_retention(_existing_tiers(args.dest), today, weekly_day=weekly_day)

    if args.dry_run:
        print(f"DRY-RUN {today}: daily={names['daily']} "
              f"weekly={'+' if plan['promote_weekly'] else '-'}{names['weekly']} "
              f"monthly={'+' if plan['promote_monthly'] else '-'}{names['monthly']} "
              f"prune={plan['prune']}")
        return 0

    daily_dir = os.path.join(args.dest, "daily", names["daily"])
    partial = daily_dir + ".partial"
    os.makedirs(os.path.dirname(daily_dir), exist_ok=True)
    shutil.rmtree(partial, ignore_errors=True)

    rc = run_rsync(args.root, partial, latest_snapshot(args.dest), args.excludes)
    if rc not in (0, 24):
        _log(f"rsync failed (exit {rc}) — leaving .partial, skipping promote/prune.")
        return 4
    os.replace(partial, daily_dir)

    if plan["promote_weekly"]:
        wdir = os.path.join(args.dest, "weekly", names["weekly"])
        if not os.path.exists(wdir):
            promote(daily_dir, wdir)
    if plan["promote_monthly"]:
        mdir = os.path.join(args.dest, "monthly", names["monthly"])
        if not os.path.exists(mdir):
            promote(daily_dir, mdir)

    for tier, victims in plan["prune"].items():
        prune_dirs([os.path.join(args.dest, tier, n) for n in victims])

    _log(f"snapshot {names['daily']} ok; prune={plan['prune']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest tests/test_backup_to_nas.py -v`
Expected: PASS (entire file).

- [ ] **Step 5: Run the whole suite + lint**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && python -m pytest -q && make check 2>/dev/null || true`
Expected: all tests pass (no regressions in the existing suite).

- [ ] **Step 6: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add scripts/backup_to_nas.py tests/test_backup_to_nas.py
git commit -m "feat(backup): main orchestration — guard, atomic commit, promote, prune"
```

---

### Task 6: `setup.sh` — install the root cron drop-in

**Files:**
- Modify: `setup.sh` (insert a new numbered section immediately after section "7. Mount backup HDD", before "8. GitHub SSH key check")

- [ ] **Step 1: Add the cron-install section**

In `setup.sh`, find the line `# ── 8. GitHub SSH key check ─────` and insert this block
**immediately before it** (keep the surrounding `info`/`warn` helper style; `HA_DIR` and
`MAIN_USER` are already defined earlier in the script):

```bash
# ── 7b. NAS snapshot cron ─────────────────────────────────────────────────────
# Versioned daily GFS snapshot of durable HA state (scripts/backup_to_nas.py).
# Installed as a root cron.d drop-in so it survives rebuilds (the script reads
# dirs owned by nobody/root/container UIDs, so it must run as root).
CRON_DROPIN="/etc/cron.d/nas-snapshot"
cat > "$CRON_DROPIN" <<CRON
# Managed by setup.sh — daily NAS snapshot (backlog #14). Do not hand-edit.
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 4 * * * root /usr/bin/python3 ${HA_DIR}/scripts/backup_to_nas.py >/dev/null 2>&1
CRON
chmod 644 "$CRON_DROPIN"
info "Installed NAS snapshot cron at ${CRON_DROPIN} (daily 04:00, as root)"
warn "Old per-file backup crons in ${MAIN_USER}'s crontab are superseded — remove them:"
warn "  sudo -u ${MAIN_USER} crontab -e   # delete the z2m / fans.yaml / rf_codes_cache lines"
```

- [ ] **Step 2: Syntax-check the script**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && bash -n setup.sh`
Expected: no output (exit 0 — valid bash).

- [ ] **Step 3: Verify the rendered cron line shape**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && HA_DIR=/home/yossi/homeassistant MAIN_USER=yossi bash -c 'sed -n "/7b. NAS snapshot/,/Old per-file/p" setup.sh' | grep -n "backup_to_nas.py"`
Expected: shows the line containing `0 4 * * * root /usr/bin/python3 ${HA_DIR}/scripts/backup_to_nas.py` (literal `${HA_DIR}` in the heredoc source is fine — it expands at runtime).

- [ ] **Step 4: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add setup.sh
git commit -m "feat(backup): install nas-snapshot root cron via setup.sh (folds #15)"
```

---

### Task 7: Update `docs/state-of-world.md`

**Files:**
- Modify: `docs/state-of-world.md` (backlog item #14, lines ~170-177)

- [ ] **Step 1: Mark #14 done and add #15**

Replace the `14. **Versioned NAS snapshots ...**` backlog entry (the whole paragraph,
currently lines ~170-177) with:

```markdown
14. ✅ **Versioned NAS snapshots** *(done — `scripts/backup_to_nas.py` + `backup-exclude.txt`,
    installed as a root `/etc/cron.d/nas-snapshot` drop-in by `setup.sh`)* — daily GFS
    snapshots (7 daily + 4 weekly + 12 monthly) of the durable HA tree to
    `/mnt/nas/snapshots/`, hardlink-dedup'd via `rsync --link-dest` (plain browsable
    dirs; restore = `cp`). Excludes the big transient live-writers — `prometheus/data/`
    and `config/home-assistant_v2.db*` (recorder DB is in HA native backups). Runs as
    root to read all owners; mount-guarded; atomic `.partial` commit. Replaces the three
    old per-file mirror crons and folds the un-versioned-crons gap (cron now lives in
    `setup.sh`).
15. **Delete superseded NAS mirrors** — once the snapshot tier has run a few cycles and a
    test restore is confirmed, remove the now-redundant `/mnt/nas/z2m/` and
    `/mnt/nas/ha-templates/` mirrors and the three old per-file crons from `yossi`'s
    crontab. Kept during cutover as a safety net.
```

- [ ] **Step 2: Verify the doc reads correctly**

Run: `cd /Users/yossi_solomon/dev/HomeAutomationSetup && grep -n "14. ✅\|15. \*\*Delete superseded" docs/state-of-world.md`
Expected: both lines present.

- [ ] **Step 3: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add docs/state-of-world.md
git commit -m "docs: mark #14 done, add #15 (delete superseded mirrors)"
```

---

## Deployment & Verification (on blacky, after merge)

These run on blacky against the real NAS — not part of the test suite. Do them after the
branch is merged and pulled on blacky.

- [ ] **First snapshot (dry-run then real):**
  ```bash
  ssh blacky 'sudo python3 /home/yossi/homeassistant/scripts/backup_to_nas.py --dry-run'
  ssh blacky 'sudo python3 /home/yossi/homeassistant/scripts/backup_to_nas.py'
  ssh blacky 'sudo ls -la /mnt/nas/snapshots/daily/'
  ```
  Expect today's `daily/<date>/` present and browsable; no `prometheus/`, no `*_v2.db` inside.

- [ ] **Exclude check:**
  ```bash
  ssh blacky 'sudo find /mnt/nas/snapshots/daily/$(date +%F) -name "home-assistant_v2.db" -o -path "*prometheus/data*" | head'
  ```
  Expect empty output.

- [ ] **Idempotent re-run (same day):**
  ```bash
  ssh blacky 'sudo python3 /home/yossi/homeassistant/scripts/backup_to_nas.py && echo OK'
  ```
  Expect `OK`, no duplicate/error.

- [ ] **Hardlink dedup proof (simulate two days):**
  ```bash
  ssh blacky 'sudo python3 /home/yossi/homeassistant/scripts/backup_to_nas.py --date 2026-06-01
              sudo python3 /home/yossi/homeassistant/scripts/backup_to_nas.py --date 2026-06-02
              sudo du -sh --apparent-size /mnt/nas/snapshots/daily/2026-06-0{1,2}
              sudo du -sh /mnt/nas/snapshots'   # real (linked) usage ≪ apparent ×2
  ```
  Expect total real usage ≈ one snapshot, not two.

- [ ] **GFS tiers across a week/month boundary:**
  ```bash
  ssh blacky 'for d in 2026-06-01 2026-06-08 2026-06-15; do sudo python3 /home/yossi/homeassistant/scripts/backup_to_nas.py --date $d; done
              sudo ls /mnt/nas/snapshots/weekly /mnt/nas/snapshots/monthly'
  ```
  Expect `weekly/` and `monthly/` populated; counts within caps.

- [ ] **Restore test:**
  ```bash
  ssh blacky 'sudo cp /mnt/nas/snapshots/daily/$(date +%F)/zigbee2mqtt/data/configuration.yaml /tmp/restore-check.yaml && head /tmp/restore-check.yaml'
  ```
  Expect intact file contents.

- [ ] **Mount guard:**
  ```bash
  ssh blacky 'sudo python3 /home/yossi/homeassistant/scripts/backup_to_nas.py --mount /tmp/definitely-not-mounted; echo "exit=$?"'
  ```
  Expect `exit=3` and a "not mounted" message; nothing written.

- [ ] **Clean up the simulated-date snapshots:**
  ```bash
  ssh blacky 'sudo rm -rf /mnt/nas/snapshots/daily/2026-06-0{1,2} /mnt/nas/snapshots/daily/2026-06-15 /mnt/nas/snapshots/weekly/* /mnt/nas/snapshots/monthly/*'
  ```

- [ ] **Cron drop-in (after running `setup.sh`, or install manually for now):**
  ```bash
  ssh blacky 'cat /etc/cron.d/nas-snapshot 2>/dev/null || echo "not yet installed — run setup.sh or install the drop-in manually"'
  ```

---

## Self-Review notes

- **Spec coverage:** layout+mechanism → Tasks 3/4/5; GFS retention → Task 2; excludes →
  Task 1; root cron + setup.sh (#15 fold) → Task 6; mount guard + atomic + exit-code
  handling → Task 5; docs/#15 → Task 7. All spec sections mapped.
- **Type consistency:** `plan_retention` returns `{"names","promote_weekly","promote_monthly","prune"}`
  used identically in Task 5 `main`. `latest_snapshot`→`run_rsync(link_dest=...)`,
  `tier_names` keys (`daily/weekly/monthly`) consistent across Tasks 2/3/5.
- **YAGNI:** no sqlite `.backup`, no container stop, no off-site replication (all
  out-of-scope per spec).
```
