# NAS Snapshot Retention — Design

> Backlog #14. Replaces the ad-hoc mirror crons with versioned, retained, dedup'd
> point-in-time snapshots of blacky's durable Home Assistant state.

## Problem

blacky's three 04:00 backup crons are mirrors, not history:

```
0 4 * * * rsync -a --delete .../zigbee2mqtt/data/ /mnt/nas/z2m/        # mirror — --delete
0 4 * * * rsync -a .../config/template/fans.yaml /mnt/nas/ha-templates/  # overwrite
0 4 * * * rsync -a .../scripts/rf_codes_cache.json /mnt/nas/ha-templates/ # overwrite
```

A source deletion or corruption (z2m DB wipe, bad config write) propagates to the NAS
within a day with **no recovery point**. The crons also live only in blacky's user
crontab — un-versioned, lost on rebuild (the flagged #15 gap).

## Verified current state (blacky, read-only inventory)

- **NAS:** `/mnt/nas` = 458 G, **452 G free** (1 % used). Space is a non-constraint.
- **HA native backups** already write dated, HA-retained tarballs to `/mnt/nas/ha/` —
  separate concern, left untouched.
- **Per-dir size + owner** under `/home/yossi/homeassistant/`:

  | Dir | Size | Owner | Note |
  |-----|------|-------|------|
  | config | 244 M | yossi | incl. `home-assistant_v2.db` 119 M (recorder, churns, regenerates); `.storage` 4.5 M = tokens/entities/HACS |
  | prometheus/data | 1.7 G | nobody | live TSDB, churns, transient, regenerates |
  | mosquitto | 54 M | yossi | retained msgs + DB + `config/passwd` (hashed creds) |
  | grafana/data | 31 M | (container UID) | sqlite; dashboards provisioned in git |
  | zigbee2mqtt/data | 3.3 M | yossi | z2m config (runtime-rewritten) + network keys |
  | nodered/data | 72 K | yossi | flows in git; creds/runtime not |
  | portainer/data | 280 K | root | |
  | esphome/config | 12 K | root | |
  | **total** | **2.0 G** | | |

## Decisions (locked during brainstorming)

1. **Architecture:** one versioned `scripts/backup_to_nas.py` + tracked exclude file,
   installed as a single root cron by `setup.sh`. Folds #15 (crons become versioned +
   rebuildable). Replaces the three ad-hoc crontab lines.
2. **Retention:** GFS — 7 daily + 4 weekly + 12 monthly (~23 snapshots, ~1 year reach).
3. **Coverage:** the **whole `homeassistant/` tree EXCEPT** the big transient
   live-writers — `prometheus/data/` (1.7 G, churns, regenerates) and
   `config/home-assistant_v2.db*` (119 M recorder, already in HA native backup). These
   are also the only real hot-copy torn-read risks. Everything else (~300 M naive,
   mostly static → dedup'd near-free) is captured: `.storage`, mosquitto `passwd`, z2m,
   nodered, grafana, portainer, esphome, all yaml.
4. **Mechanism:** hand-rolled `rsync --link-dest` hardlink snapshots — plain browsable
   dirs, restore = `cp`, no new dependency. (Rejected: `--backup-dir` diffs → restore
   pain; restic/borg → binary dep + opaque repo for 300 M of eyeball-able files.)
5. **Run as root** — only way to read the `nobody`/`root`/container-UID owned dirs.
6. The **superseded mirrors** (`/mnt/nas/z2m/`, `/mnt/nas/ha-templates/`) are **not**
   deleted by this work — kept as a cutover safety net; deletion becomes backlog #15.

## Architecture

### Snapshot layout

```
/mnt/nas/snapshots/            # root:root, 0700 (holds passwd + .storage tokens)
  daily/2026-06-11/            # full tree, hardlinked vs previous snapshot
  daily/2026-06-10/
  weekly/2026-W23/
  monthly/2026-06/
```

### Per-run flow (`backup_to_nas.py`)

1. **Guard:** abort unless `/mnt/nas` is a mountpoint (`mountpoint -q`) — never write
   snapshots onto the local root fs if the HDD is unmounted.
2. **Copy:** `rsync -a --delete --link-dest=<prev> --exclude-from=backup-exclude.txt
   <root>/ <dest>/daily/<date>.partial/`, where `<prev>` = most recent existing
   snapshot across all tiers (continuous hardlink chain). Unchanged files at any depth
   share inodes with `<prev>` → near-zero disk.
3. **Atomic commit:** on rsync exit 0 or 24 (24 = files vanished mid-copy, normal for
   live dirs), `mv` `<date>.partial/` → `<date>/`. Any other exit → log, exit non-zero,
   **skip promotion + prune** (don't prune good snapshots after a failed copy). A
   crashed run leaves only a `.partial` (cleaned next run), never a half-snapshot that
   the next `--link-dest` could anchor to.
4. **Promote:** if today is the configured weekly day (default Monday) → hardlink
   today's daily into `weekly/<ISO-week>/`. If day-of-month == 01 → into
   `monthly/<YYYY-MM>/`. Promotion re-links, never re-copies.
5. **Prune:** per tier, keep newest N (daily 7, weekly 4, monthly 12); `rm -rf` the
   rest. Hardlinked inodes shared with surviving snapshots persist — only the extra
   directory entry is removed. Safe by construction.
6. **Log:** `logger -t nas-snapshot` + summary (snapshot size, per-tier counts, prune
   actions).

### Excludes (`scripts/backup-exclude.txt`, tracked)

```
prometheus/data/
config/home-assistant_v2.db
config/home-assistant_v2.db-shm
config/home-assistant_v2.db-wal
*.log
.git/
**/node_modules/
**/__pycache__/
```

### CLI surface

```
backup_to_nas.py [--dry-run] [--date YYYY-MM-DD] \
                 [--root /home/yossi/homeassistant] [--dest /mnt/nas/snapshots] \
                 [--weekly-day mon]
```

`--date` injects "today" → deterministic retention tests. `--dry-run` logs the plan
without touching disk. Defaults match blacky.

### Testable core (pure functions)

- `plan_retention(existing_by_tier, today, weekly_day) -> {keep, prune, promote}` —
  given existing snapshot dates per tier + today, returns keep/prune/promote sets.
  No wall-clock reads (today injected).
- `load_excludes(path) -> [patterns]` — parse exclude file, skip comments/blanks.
- `latest_snapshot(dest) -> path|None` — newest snapshot across tiers for `--link-dest`.

`main()` is the thin imperative shell: guard → rsync (subprocess) → atomic mv →
promote → prune → log.

## Deployment / versioning (folds #15)

- Script + exclude file live in the repo, checked out on blacky at
  `/home/yossi/homeassistant/scripts/` (blacky runs HA from the repo) — no separate
  deploy step.
- `setup.sh` idempotently installs `/etc/cron.d/nas-snapshot` from a tracked template:

  ```
  0 4 * * * root /usr/bin/python3 /home/yossi/homeassistant/scripts/backup_to_nas.py >/dev/null 2>&1
  ```

  A drop-in (not root crontab) — itself a tracked artifact; a rebuild restores it.
- The three old user crons are removed from blacky's user crontab during cutover
  (manual step — user crontab is un-versioned; documented in the plan).

## Files created / modified

- `scripts/backup_to_nas.py` (new) — pure functions + thin `main()`. Stdlib only.
- `scripts/backup-exclude.txt` (new) — rsync exclude patterns.
- `setup.sh` (modify) — idempotent `/etc/cron.d/nas-snapshot` install.
- `tests/test_backup_to_nas.py` (new) — pytest, mirrors `test_gen_hacs_manifest.py`.
- `docs/state-of-world.md` (modify) — mark #14 done; add #15 (delete superseded
  mirrors once snapshots proven + restore-tested); record root cron + snapshot tree.

## Testing

Pure-function units, deterministic via injected `--date`:

- `plan_retention`: daily keeps newest 7 / prunes 8th+; weekly capped 4; monthly capped
  12; empty input → no prune; promotion fires only on configured weekday / day-01.
- `load_excludes`: comments + blank lines ignored; patterns preserved in order.
- mountpoint guard: returns abort when dest not a mountpoint (mocked).
- rsync exit handling: 0 and 24 → success; other non-zero → no promotion/prune (mocked
  subprocess).
- `--dry-run`: plans without filesystem writes.

## Verification (on blacky, post-deploy)

1. Manual run → `snapshots/daily/<today>/` appears, browsable; excludes absent (no
   `prometheus/`, no `*_v2.db`).
2. Second run same day → idempotent (re-link, no duplicate / no error).
3. Inject `--date` across a fake week + month boundary → weekly/monthly tiers populate
   and prune to caps.
4. `du -sh` first vs second snapshot → second ≪ first (hardlink dedup confirmed).
5. Restore: `cp` a file out of a snapshot → intact.
6. mountpoint guard: bad `--dest` / unmount-sim → aborts, no local-fs write.

## Known limitations

- Hot-copy of the small remaining live-writers (grafana sqlite, mosquitto DB,
  `.storage`) can capture a torn state. Low-stakes (regenerable / corrected next
  snapshot); not worth container-stop or sqlite `.backup` complexity (YAGNI).
- Recorder DB (`home-assistant_v2.db`) and prometheus metrics are intentionally **not**
  snapshotted here — recorder is in HA native backups; prometheus metrics regenerate.

## Out of scope

- Deleting the superseded `/mnt/nas/z2m/` + `/mnt/nas/ha-templates/` mirrors (→ #15).
- Off-site / 3-2-1 replication of the NAS itself.
- Snapshotting prometheus TSDB or the HA recorder DB.
