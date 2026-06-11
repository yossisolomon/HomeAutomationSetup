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
