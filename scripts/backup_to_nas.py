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
