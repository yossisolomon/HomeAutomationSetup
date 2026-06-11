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
    # 2026-06-01 day==1 forces monthly; set weekly_day to 6 to avoid asserting weekly
    rc = b.main(["--root", str(tmp_path), "--dest", str(dest), "--mount", str(tmp_path),
                 "--excludes", str(ex), "--date", "2026-06-01", "--weekly-day", "6"])
    assert rc == 0
    assert (dest / "daily" / "2026-06-01").is_dir()        # .partial committed
    assert not (dest / "daily" / "2026-06-01.partial").exists()
    assert (str(dest / "daily" / "2026-06-01"),
            str(dest / "monthly" / "2026-06")) in promotes  # monthly promo on the 1st
