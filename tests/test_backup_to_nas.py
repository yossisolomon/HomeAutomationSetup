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
