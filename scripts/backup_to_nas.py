"""Take GFS-tiered, hardlink-dedup'd snapshots of blacky's durable HA state to the NAS.

Runs as root from cron (reads dirs owned by nobody/root/container UIDs). Pure
functions (retention math, snapshot discovery) + a thin imperative main(). Stdlib
only. See docs/superpowers/specs/2026-06-11-nas-snapshot-retention-design.md.
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys


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
    """Absolute path to the newest committed snapshot to use as the --link-dest anchor.

    Prefers the newest daily (always freshest, since a daily is written every run);
    falls back to the newest weekly then monthly so dedup survives even if dailies were
    cleared. Ignores `.partial` dirs. Names sort chronologically within a tier, so the
    newest is the lexical max. Returns None if no snapshot exists (first run -> full copy).
    """
    for tier in ("daily", "weekly", "monthly"):
        d = os.path.join(dest, tier)
        if not os.path.isdir(d):
            continue
        names = [n for n in os.listdir(d)
                 if not n.endswith(".partial") and os.path.isdir(os.path.join(d, n))]
        if names:
            return os.path.join(d, max(names))
    return None


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
    if wd in WEEKDAYS:
        weekly_day = WEEKDAYS.index(wd)
    else:
        try:
            weekly_day = int(wd)
        except ValueError:
            p.error(f"--weekly-day must be mon..sun or 0..6, got {args.weekly_day!r}")
        if not 0 <= weekly_day <= 6:
            p.error(f"--weekly-day must be 0..6, got {weekly_day}")

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
            os.makedirs(os.path.dirname(wdir), exist_ok=True)
            promote(daily_dir, wdir)
    if plan["promote_monthly"]:
        mdir = os.path.join(args.dest, "monthly", names["monthly"])
        if not os.path.exists(mdir):
            os.makedirs(os.path.dirname(mdir), exist_ok=True)
            promote(daily_dir, mdir)

    for tier, victims in plan["prune"].items():
        prune_dirs([os.path.join(args.dest, tier, n) for n in victims])

    _log(f"snapshot {names['daily']} ok; prune={plan['prune']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
