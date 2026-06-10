# IR Code-Set Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** A standalone CLI that captures an unknown AC's real IR remote, identifies which `ar_smart_ir` climate code-set matches, and reports manufacturer/model/device_code for a one-off manual UI config.

**Architecture:** A self-contained trio under `scripts/` depending only on `python-broadlink` + stdlib (jq optional): `ir_codec.py` (pure broadlink-IR ↔ pulse-tick codec), `ir_match.py` (pure mini-DB load + similarity scoring), and `find_ir_codeset.py` (CLI orchestrator: DB fetch → capture → median-clean → match → adaptive disambiguation → replay-confirm → report). The DB is sparse-cloned into `/tmp` on demand and reduced to a compact `mini_db.ndjson` cache (jq-parallel, Python fallback).

**Tech Stack:** Python 3.11 (pyenv venv `homeautomation`), `python-broadlink`, pytest, jq (optional), git.

**Spec:** `docs/superpowers/specs/2026-06-09-ir-codeset-finder-design.md`

**Conventions for every task below:**
- Run python/pytest through the venv. If `.python-version` auto-activation isn't working, prefix with `pyenv exec` or `~/.pyenv/versions/homeautomation/bin/`.
- All commits exclude the `/tmp` DB and `mini_db.ndjson` (never in the repo).

---

### Task 1: Environment + module scaffolding

**Files:**
- Modify: `requirements-dev.txt`
- Create: `scripts/ir_codec.py`, `scripts/ir_match.py`, `scripts/find_ir_codeset.py` (empty stubs)
- Create: `tests/test_ir_codec.py`, `tests/test_ir_match.py`, `tests/test_find_ir_codeset.py` (empty)

- [x] **Step 1: Ensure deps in the venv**

Run (one line; pip pointed at public PyPI per Forter default):
```bash
~/.pyenv/versions/homeautomation/bin/pip install --index-url https://pypi.org/simple/ \
  -r scripts/requirements.txt -r requirements-dev.txt
```
Expected: `broadlink`, `pytest`, `PyYAML`, `yamllint` all "already satisfied" or freshly installed.

- [x] **Step 2: Verify the toolchain**

Run:
```bash
~/.pyenv/versions/homeautomation/bin/python -c "import broadlink, pytest; print('ok')"
```
Expected: `ok`

- [x] **Step 3: Create empty module + test files**

```bash
: > scripts/ir_codec.py
: > scripts/ir_match.py
: > scripts/find_ir_codeset.py
: > tests/test_ir_codec.py
: > tests/test_ir_match.py
: > tests/test_find_ir_codeset.py
```

- [x] **Step 4: Commit**

```bash
git add scripts/ir_codec.py scripts/ir_match.py scripts/find_ir_codeset.py \
        tests/test_ir_codec.py tests/test_ir_match.py tests/test_find_ir_codeset.py requirements-dev.txt
git commit -m "chore(ir): scaffold IR code-set finder modules + tests"
```

---

### Task 2: `ir_codec` — decode broadlink Base64 → pulse ticks

**Files:**
- Modify: `scripts/ir_codec.py`
- Test: `tests/test_ir_codec.py`

The real `off` packet from `codes/climate/1000.json` is the fixture. It decodes to **140 pulses** starting `[297, 145, 23, 52, 24, 16, 23, 17, 23, 16, 23, 53]` (9 ms / 4.5 ms NEC leader; 1 tick ≈ 30.52 µs).

- [x] **Step 1: Write the failing test**

```python
# tests/test_ir_codec.py
import pytest
from scripts import ir_codec

OFF_1000 = (
    "JgCSAAABKZEXNBgQFxEXEBc1FxAYEBcQGDQXERcQGDQXERcQFxEXEBcRFxAYEBcQGBAXNRcQ"
    "FxEXEBcRFxAYEBc1FxAXNRcQGBAXNRcQFwACjhcQGBAXEBgQFxEXEBcRFxAXERcQGBAXEBgQ"
    "FzQYEBcRFxAYEBcQGBAXEBgQFxEXEBcRFxAXERcQGBAXNBg0FxEXAA0FAAAAAAAA"
)

def test_decode_broadlink_b64_known_packet():
    pulses = ir_codec.decode_broadlink_b64(OFF_1000)
    assert len(pulses) == 140
    assert pulses[:12] == [297, 145, 23, 52, 24, 16, 23, 17, 23, 16, 23, 53]

def test_decode_rejects_non_ir_packet():
    import base64
    rf = base64.b64encode(bytes([0xb2, 0x00, 0x02, 0x00, 0x10, 0x20])).decode()
    with pytest.raises(ValueError):
        ir_codec.decode_broadlink_b64(rf)
```

Note: tests import `from scripts import ir_codec`. Add an empty `scripts/__init__.py` and `tests/__init__.py` if not present, and run pytest from the repo root.

- [x] **Step 2: Run test to verify it fails**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_codec.py -v`
Expected: FAIL (`module 'ir_codec' has no attribute 'decode_broadlink_b64'`).

- [x] **Step 3: Implement**

```python
# scripts/ir_codec.py
"""Pure broadlink-IR <-> pulse-tick codec. No I/O, no hardware.

A broadlink IR packet: byte0=0x26 (IR), byte1=repeat, bytes2-3=little-endian
payload length, then the pulse stream (1 byte per pulse, or 0x00 + 2 big-endian
bytes for pulses > 255), then a 0x00 0x0d 0x05 trailer. One tick is 2**-15 s.
"""
import base64

TICK_US = 1_000_000 / 32768  # ~30.5176 microseconds per tick


def decode_broadlink_b64(b64: str) -> list[int]:
    data = base64.b64decode(b64)
    if not data or data[0] != 0x26:
        raise ValueError(f"not a broadlink IR packet (byte0={data[:1].hex()})")
    length = data[2] | (data[3] << 8)
    i, end, pulses = 4, 4 + length, []
    while i < end:
        b = data[i]
        if b == 0:
            pulses.append((data[i + 1] << 8) | data[i + 2])
            i += 3
        else:
            pulses.append(b)
            i += 1
    return pulses
```

- [x] **Step 4: Run test to verify it passes**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_codec.py -v`
Expected: PASS (2 passed).

- [x] **Step 5: Commit**

```bash
git add scripts/ir_codec.py tests/test_ir_codec.py scripts/__init__.py tests/__init__.py
git commit -m "feat(ir): decode broadlink Base64 IR packets to pulse ticks"
```

---

### Task 3: `ir_codec` — encode ticks → broadlink bytes (round-trip)

**Files:**
- Modify: `scripts/ir_codec.py`
- Test: `tests/test_ir_codec.py`

Encode is needed only to replay Raw-encoded candidates (Base64 candidates replay their stored packet verbatim). Correctness is proven by round-trip: `decode(encode(x)) == x`.

- [x] **Step 1: Write the failing test**

```python
# append to tests/test_ir_codec.py
def test_encode_decode_round_trip():
    pulses = [297, 145, 23, 52, 300, 16, 70000 % 65536, 256, 1]
    out = ir_codec.encode_broadlink(pulses)
    assert out[0] == 0x26
    assert ir_codec.decode_broadlink_b64(__import__("base64").b64encode(out).decode()) == pulses
```

- [x] **Step 2: Run test to verify it fails**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_codec.py::test_encode_decode_round_trip -v`
Expected: FAIL (`no attribute 'encode_broadlink'`).

- [x] **Step 3: Implement**

```python
# append to scripts/ir_codec.py
def encode_broadlink(ticks: list[int]) -> bytes:
    body = bytearray()
    for v in ticks:
        if v > 255:
            body += bytes([0x00, (v >> 8) & 0xFF, v & 0xFF])
        else:
            body.append(v & 0xFF)
    header = bytes([0x26, 0x00, len(body) & 0xFF, (len(body) >> 8) & 0xFF])
    return bytes(header) + bytes(body) + b"\x00\x0d\x05"
```

- [x] **Step 4: Run test to verify it passes**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_codec.py -v`
Expected: PASS (3 passed).

- [x] **Step 5: Commit**

```bash
git add scripts/ir_codec.py tests/test_ir_codec.py
git commit -m "feat(ir): encode pulse ticks to broadlink IR bytes (round-trip)"
```

---

### Task 4: `ir_codec` — Raw (signed-µs string) → ticks, and Base64 passthrough

**Files:**
- Modify: `scripts/ir_codec.py`
- Test: `tests/test_ir_codec.py`

SmartIR Raw commands are space-separated signed µs strings, e.g. `"9040 -4410 650 -1590 …"` (sign marks mark/space; magnitude is duration). `9040 µs / 30.5176 ≈ 296` ticks — matching the Base64 leader.

- [x] **Step 1: Write the failing test**

```python
# append to tests/test_ir_codec.py
def test_raw_to_ticks_signed_us_string():
    ticks = ir_codec.raw_to_ticks("9040 -4410 650 -1590")
    assert ticks == [296, 145, 21, 52]

def test_raw_to_ticks_accepts_list():
    assert ir_codec.raw_to_ticks([9040, -4410]) == [296, 145]

def test_b64_to_bytes():
    assert ir_codec.b64_to_bytes("JgA=") == b"\x26\x00"
```

- [x] **Step 2: Run test to verify it fails**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_codec.py -k "raw or b64_to_bytes" -v`
Expected: FAIL (`no attribute 'raw_to_ticks'`).

- [x] **Step 3: Implement**

```python
# append to scripts/ir_codec.py
def raw_to_ticks(raw) -> list[int]:
    tokens = raw.split() if isinstance(raw, str) else raw
    return [round(abs(int(x)) / TICK_US) for x in tokens]


def b64_to_bytes(b64: str) -> bytes:
    return base64.b64decode(b64)
```

- [x] **Step 4: Run test to verify it passes**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_codec.py -v`
Expected: PASS (6 passed).

- [x] **Step 5: Commit**

```bash
git add scripts/ir_codec.py tests/test_ir_codec.py
git commit -m "feat(ir): parse Raw signed-us commands to ticks; add b64_to_bytes"
```

---

### Task 5: `ir_match` — similarity scoring + entry decoding

**Files:**
- Modify: `scripts/ir_match.py`
- Test: `tests/test_ir_match.py`

Score gates on pulse-count (within ±`count_slack`), then returns the percentage of aligned pulses within ±`tol` relative tolerance.

- [x] **Step 1: Write the failing test**

```python
# tests/test_ir_match.py
from scripts import ir_match

def test_score_identical_is_100():
    ref = [297, 145, 23, 52, 24]
    assert ir_match.score(ref, list(ref)) == 100.0

def test_score_jittered_within_tol_is_high():
    ref = [300, 150, 20, 50, 20]
    cand = [330, 165, 22, 45, 18]  # ~10% jitter, within default 15%
    assert ir_match.score(ref, cand) == 100.0

def test_score_count_mismatch_is_zero():
    assert ir_match.score([1, 2, 3], [1, 2, 3, 4, 5, 6]) == 0.0

def test_score_partial():
    ref = [100, 100, 100, 100]
    cand = [100, 100, 999, 999]  # 2 of 4 within tol
    assert ir_match.score(ref, cand) == 50.0

def test_entry_to_ticks_base64():
    entry = {"enc": "Base64", "off": "JgAGAAABKQEpAA0F"}
    ticks = ir_match.entry_to_ticks(entry)
    assert isinstance(ticks, list) and ticks  # decodes without error

def test_entry_to_ticks_raw():
    entry = {"enc": "Raw", "off": "9040 -4410"}
    assert ir_match.entry_to_ticks(entry) == [296, 145]

def test_entry_to_ticks_missing_off_returns_none():
    assert ir_match.entry_to_ticks({"enc": "Base64", "off": None}) is None
```

- [x] **Step 2: Run test to verify it fails**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_match.py -v`
Expected: FAIL (`No module named ... attribute 'score'`).

- [x] **Step 3: Implement**

```python
# scripts/ir_match.py
"""Pure matching: decode DB entries and score them against a reference. No I/O."""
from scripts import ir_codec


def score(ref: list[int], cand: list[int], tol: float = 0.15, count_slack: int = 2) -> float:
    if not ref or not cand:
        return 0.0
    if abs(len(ref) - len(cand)) > count_slack:
        return 0.0
    n = min(len(ref), len(cand))
    hits = sum(1 for a, b in zip(ref[:n], cand[:n]) if abs(a - b) <= tol * max(a, b, 1))
    return 100.0 * hits / n


def entry_to_ticks(entry: dict) -> list[int] | None:
    off = entry.get("off")
    if not off:
        return None
    enc = (entry.get("enc") or "").lower()
    try:
        if enc == "base64":
            return ir_codec.decode_broadlink_b64(off)
        if enc == "raw":
            return ir_codec.raw_to_ticks(off)
    except Exception:
        return None
    return None
```

- [x] **Step 4: Run test to verify it passes**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_match.py -v`
Expected: PASS (7 passed). If `test_entry_to_ticks_base64`'s tiny packet raises, replace its `off` with `OFF_1000` imported from the codec test — the assertion only checks it decodes to a non-empty list.

- [x] **Step 5: Commit**

```bash
git add scripts/ir_match.py tests/test_ir_match.py
git commit -m "feat(ir): pulse-similarity scoring + DB entry decoding"
```

---

### Task 6: `ir_match` — mini-DB load, ranking, tie detection

**Files:**
- Modify: `scripts/ir_match.py`
- Test: `tests/test_ir_match.py`

`mini_db.ndjson` has one JSON object per line: `{device_code, manufacturer, models, enc, off}`.

- [x] **Step 1: Write the failing test**

```python
# append to tests/test_ir_match.py
import json

def _write_ndjson(tmp_path, rows):
    p = tmp_path / "mini_db.ndjson"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(p)

def test_load_mini_db_skips_blank_and_offless(tmp_path):
    path = _write_ndjson(tmp_path, [
        {"device_code": "1", "enc": "Raw", "off": "100 -100"},
        {"device_code": "2", "enc": "Raw", "off": None},
    ])
    rows = ir_match.load_mini_db(path)
    assert [r["device_code"] for r in rows] == ["1"]

def test_rank_orders_by_score(tmp_path):
    ref = [100, 100, 100, 100]
    entries = [
        # 3052 us ~= 100 ticks -> scores 100% vs ref; 30520 us ~= 1000 ticks -> rejected by tol
        {"device_code": "near", "enc": "Raw", "off": "3052 3052 3052 3052"},
        {"device_code": "far", "enc": "Raw", "off": "30520 30520 30520 30520"},
    ]
    ranked = ir_match.rank(ref, entries)
    assert ranked[0]["device_code"] == "near"
    assert ranked[0]["score"] >= ranked[1]["score"]

def test_is_tie_true_when_top_two_close():
    ranked = [{"score": 95.0}, {"score": 94.0}, {"score": 10.0}]
    assert ir_match.is_tie(ranked) is True

def test_is_tie_false_when_clear_winner():
    ranked = [{"score": 95.0}, {"score": 40.0}]
    assert ir_match.is_tie(ranked) is False
```

Note: `3052 µs ≈ 100 ticks`, so the "near" entry scores 100% against `ref=[100,100,100,100]`; "far" (30520 µs ≈ 1000 ticks) is rejected by tolerance → lower.

- [x] **Step 2: Run test to verify it fails**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_match.py -k "mini_db or rank or tie" -v`
Expected: FAIL (`no attribute 'load_mini_db'`).

- [x] **Step 3: Implement**

```python
# append to scripts/ir_match.py
import json


def load_mini_db(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("off"):
                rows.append(row)
    return rows


def rank(ref: list[int], entries: list[dict], **kw) -> list[dict]:
    scored = []
    for entry in entries:
        cand = entry_to_ticks(entry)
        if cand is None:
            continue
        scored.append({**entry, "score": score(ref, cand, **kw)})
    scored.sort(key=lambda e: e["score"], reverse=True)
    return scored


def is_tie(ranked: list[dict], margin: float = 3.0) -> bool:
    return len(ranked) >= 2 and (ranked[0]["score"] - ranked[1]["score"]) < margin
```

- [x] **Step 4: Run test to verify it passes**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_ir_match.py -v`
Expected: PASS (11 passed).

- [x] **Step 5: Commit**

```bash
git add scripts/ir_match.py tests/test_ir_match.py
git commit -m "feat(ir): mini-DB load, ranking, and tie detection"
```

---

### Task 7: `find_ir_codeset` — pure helpers (clean captures, report)

**Files:**
- Modify: `scripts/find_ir_codeset.py`
- Test: `tests/test_find_ir_codeset.py`

`clean_captures` rejects outlier-length captures and medians the survivors; needs ≥2 agreeing captures or it raises (so the orchestrator can re-prompt).

- [x] **Step 1: Write the failing test**

```python
# tests/test_find_ir_codeset.py
import pytest
from scripts import find_ir_codeset as f

def test_clean_captures_medians_agreeing():
    caps = [[100, 200, 50], [110, 190, 52], [90, 210, 48]]
    assert f.clean_captures(caps) == [100, 200, 50]

def test_clean_captures_drops_outlier_length():
    caps = [[100, 200, 50], [110, 190, 52], [1, 2]]  # last has wrong count
    assert f.clean_captures(caps) == [105, 195, 51]  # median of the two 3-length

def test_clean_captures_raises_when_all_disagree():
    with pytest.raises(ValueError):
        f.clean_captures([[1, 2], [1, 2, 3], [1, 2, 3, 4]])

def test_format_report_confirmed():
    entry = {"manufacturer": "Tornado", "models": ["RGS-XYZ"], "device_code": "1234"}
    out = f.format_report(entry, 94.0, confirmed=True)
    assert "MATCH (94%, replay-confirmed)" in out
    assert "Tornado" in out and "RGS-XYZ" in out and "1234" in out
```

- [x] **Step 2: Run test to verify it fails**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_find_ir_codeset.py -v`
Expected: FAIL (`no attribute 'clean_captures'`).

- [x] **Step 3: Implement**

```python
# scripts/find_ir_codeset.py
"""Standalone IR code-set finder. Deps: python-broadlink + stdlib (jq optional).

Capture an unknown AC's IR 'off' from its real remote, match it against the
ar_smart_ir climate code-set DB, and report manufacturer/model/device_code.

Usage:
  python3 scripts/find_ir_codeset.py --device-ip 192.168.1.19
  python3 scripts/find_ir_codeset.py --discover
  python3 scripts/find_ir_codeset.py --device-ip 192.168.1.18 --refresh-db
"""
import statistics
from collections import Counter


def clean_captures(captures: list[list[int]]) -> list[int]:
    if not captures:
        raise ValueError("no captures provided")
    counts = Counter(len(c) for c in captures)
    modal_len, _ = counts.most_common(1)[0]
    keep = [c for c in captures if len(c) == modal_len]
    if len(keep) < 2:
        raise ValueError(
            f"inconsistent captures (pulse counts {[len(c) for c in captures]}); "
            "re-capture — likely bad reception or wrong button"
        )
    return [int(statistics.median(col)) for col in zip(*keep)]


def format_report(entry: dict, match_score: float, confirmed: bool) -> str:
    tag = "replay-confirmed" if confirmed else "unconfirmed"
    models = ", ".join(entry.get("models") or []) or "?"
    return (
        f"MATCH ({match_score:.0f}%, {tag}):\n"
        f"  manufacturer : {entry.get('manufacturer', '?')}\n"
        f"  model        : {models}\n"
        f"  device_code  : {entry.get('device_code', '?')}\n"
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/test_find_ir_codeset.py -v`
Expected: PASS (4 passed).

- [x] **Step 5: Commit**

```bash
git add scripts/find_ir_codeset.py tests/test_find_ir_codeset.py
git commit -m "feat(ir): capture cleaning (median) + match report formatting"
```

---

### Task 8: `find_ir_codeset` — DB fetch + mini-DB build

**Files:**
- Modify: `scripts/find_ir_codeset.py`

DB sourcing is I/O (git + filesystem), verified manually rather than unit-tested.

- [x] **Step 1: Implement DB fetch + mini-DB build**

```python
# append to scripts/find_ir_codeset.py
import json
import os
import shutil
import subprocess

REPO_URL = "https://github.com/marsh4200/ar_smart_ir"
DEFAULT_DB_DIR = "/tmp/ar_smart_ir_db"
CLIMATE_GLOB = "codes/climate"


def ensure_db(db_dir: str, refresh: bool) -> str:
    """Clone (sparse) the code-set repo if missing; pull if --refresh-db."""
    if not os.path.isdir(os.path.join(db_dir, ".git")):
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--sparse", REPO_URL, db_dir],
            check=True,
        )
        subprocess.run(
            ["git", "-C", db_dir, "sparse-checkout", "set", "codes"], check=True
        )
    elif refresh:
        subprocess.run(["git", "-C", db_dir, "pull", "--ff-only"], check=True)
    return db_dir


def build_mini_db(db_dir: str, force: bool = False) -> str:
    """Reduce codes/climate/*.json to a compact mini_db.ndjson cache."""
    climate = os.path.join(db_dir, CLIMATE_GLOB)
    mini = os.path.join(db_dir, "mini_db.ndjson")
    if os.path.exists(mini) and not force:
        return mini
    if shutil.which("jq"):
        jq = (
            '{device_code:(input_filename|gsub(".*/";"")|gsub(".json$";"")), '
            "manufacturer, models:.supportedModels, enc:.commandsEncoding, off:.commands.off}"
        )
        nproc = str(os.cpu_count() or 4)
        with open(mini, "w", encoding="utf-8") as out:
            find = subprocess.Popen(
                ["find", climate, "-name", "*.json", "-print0"], stdout=subprocess.PIPE
            )
            subprocess.run(
                ["xargs", "-0", "-P", nproc, "-I", "{}", "jq", "-c", jq, "{}"],
                stdin=find.stdout, stdout=out, check=True,
            )
            find.stdout.close()
    else:
        with open(mini, "w", encoding="utf-8") as out:
            for name in sorted(os.listdir(climate)):
                if not name.endswith(".json"):
                    continue
                with open(os.path.join(climate, name), encoding="utf-8") as fh:
                    d = json.load(fh)
                out.write(json.dumps({
                    "device_code": name[:-5],
                    "manufacturer": d.get("manufacturer"),
                    "models": d.get("supportedModels"),
                    "enc": d.get("commandsEncoding"),
                    "off": d.get("commands", {}).get("off"),
                }) + "\n")
    return mini
```

- [x] **Step 2: Manually verify the build**

Run:
```bash
~/.pyenv/versions/homeautomation/bin/python -c \
  "from scripts import find_ir_codeset as f; d=f.ensure_db('/tmp/ar_smart_ir_db', False); m=f.build_mini_db(d, force=True); print(m); print(sum(1 for _ in open(m)), 'rows')"
```
Expected: prints the mini-DB path and ~363 rows. Re-running without `force` returns instantly.

- [x] **Step 3: Commit**

```bash
git add scripts/find_ir_codeset.py
git commit -m "feat(ir): sparse-clone code-set DB to /tmp + build mini_db.ndjson cache"
```

---

### Task 9: `find_ir_codeset` — device I/O + `main()` orchestration

**Files:**
- Modify: `scripts/find_ir_codeset.py`

Wires capture → clean → match → adaptive disambiguation → replay-confirm → report. Hardware paths verified manually (Task 10).

- [x] **Step 1: Implement device I/O + orchestration**

```python
# append to scripts/find_ir_codeset.py
import argparse
import time

from scripts import ir_codec, ir_match

LEARN_POLL_TIMEOUT = 30


def connect_device(ip: str | None, discover: bool, timeout: int):
    import broadlink
    if discover and not ip:
        devices = broadlink.discover(timeout=timeout)
        if not devices:
            raise SystemExit("no broadlink devices found on the LAN")
        dev = devices[0]
        print(f"Discovered {dev.type} at {dev.host[0]}")
    elif ip:
        dev = broadlink.hello(ip)
    else:
        raise SystemExit("provide --device-ip <ip> or --discover")
    dev.auth()
    return dev


def capture_once(dev, timeout: int) -> list[int]:
    import broadlink.exceptions
    dev.enter_learning()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.4)
        try:
            data = dev.check_data()
        except broadlink.exceptions.StorageError:
            continue
        b64 = __import__("base64").b64encode(data).decode()
        return ir_codec.decode_broadlink_b64(b64)
    raise TimeoutError("no IR packet received")


def capture(dev, label: str, n: int, timeout: int) -> list[int]:
    while True:
        caps = []
        for k in range(n):
            print(f"  Press {label} ({k + 1}/{n}) within {timeout}s ...")
            try:
                caps.append(capture_once(dev, timeout))
            except TimeoutError:
                print("  timeout — retrying this press")
        try:
            return clean_captures(caps)
        except ValueError as err:
            print(f"  {err}")
            if input("  re-capture this command? [Y/n]: ").strip().lower() == "n":
                raise SystemExit("aborted by user")


def replay(dev, entry: dict) -> None:
    off = entry["off"]
    payload = (
        ir_codec.b64_to_bytes(off)
        if (entry.get("enc") or "").lower() == "base64"
        else ir_codec.encode_broadlink(ir_codec.raw_to_ticks(off))
    )
    dev.send_data(payload)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Identify an AC's ar_smart_ir code-set from its IR remote.")
    p.add_argument("--device-ip", help="Broadlink device IP")
    p.add_argument("--discover", action="store_true", help="Scan the LAN for a Broadlink device")
    p.add_argument("--db-dir", default=DEFAULT_DB_DIR, help=f"code-set checkout dir (default {DEFAULT_DB_DIR})")
    p.add_argument("--refresh-db", action="store_true", help="git pull the code-set DB to latest")
    p.add_argument("--captures", type=int, default=3, help="captures per command (default 3)")
    p.add_argument("--timeout", type=int, default=LEARN_POLL_TIMEOUT, help="per-capture timeout seconds")
    p.add_argument("--top", type=int, default=5, help="shortlist size to show/confirm")
    p.add_argument("--controller", default="remote.<your_broadlink_entity>", help="HA remote entity for the report")
    args = p.parse_args(argv)

    db = ensure_db(args.db_dir, args.refresh_db)
    mini = build_mini_db(db, force=args.refresh_db)
    entries = ir_match.load_mini_db(mini)
    print(f"Loaded {len(entries)} code-sets from {mini}")

    dev = connect_device(args.device_ip, args.discover, args.timeout)
    print("Capturing OFF from the real remote:")
    ref = capture(dev, "OFF", args.captures, args.timeout)

    ranked = ir_match.rank(ref, entries)
    if not ranked or ranked[0]["score"] == 0.0:
        print("No candidate matched. Try --refresh-db or a cleaner capture.")
        return 1

    if ir_match.is_tie(ranked):
        print("Top candidates tie on OFF — capturing a 2nd command to disambiguate.")
        print("Set the remote to COOL, a fixed temperature, and a fixed fan speed, then send it.")
        ref2 = capture(dev, "COOL/<temp>/<fan>", args.captures, args.timeout)
        shortlist = ranked[: args.top]
        for entry in shortlist:
            full = _load_full_codeset(db, entry["device_code"])
            cand2 = _extract_cool_command(full)
            entry["score2"] = ir_match.score(ref2, cand2) if cand2 else 0.0
        shortlist.sort(key=lambda e: (e["score"] + e.get("score2", 0.0)), reverse=True)
        ranked = shortlist + ranked[args.top:]

    print("\nTop candidates:")
    for e in ranked[: args.top]:
        print(f"  {e['score']:5.1f}%  code {e['device_code']:>5}  "
              f"{e.get('manufacturer','?')}  {', '.join(e.get('models') or []) or '?'}")

    confirmed = None
    for entry in ranked[: args.top]:
        print(f"\nReplaying OFF for code {entry['device_code']} ({entry.get('manufacturer','?')}).")
        try:
            replay(dev, entry)
        except Exception as err:  # noqa: BLE001 - report and continue to next candidate
            print(f"  replay failed: {err}")
            continue
        if input("  Did the AC react? [y/N]: ").strip().lower() == "y":
            confirmed = entry
            break

    chosen = confirmed or ranked[0]
    print("\n" + format_report(chosen, chosen["score"], confirmed is not None))
    print(f"→ ar_smart_ir → Climate → manufacturer "
          f"\"{chosen.get('manufacturer','?')}\" → that model")
    print(f"→ controller entity: {args.controller}")
    return 0


def _load_full_codeset(db_dir: str, device_code: str) -> dict:
    with open(os.path.join(db_dir, CLIMATE_GLOB, f"{device_code}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _extract_cool_command(full: dict):
    """Best-effort: first cool command found, decoded to ticks. None if absent."""
    cool = (full.get("commands") or {}).get("cool")
    if not isinstance(cool, dict):
        return None
    enc = (full.get("commandsEncoding") or "").lower()
    for fan in cool.values():
        if isinstance(fan, dict):
            for cmd in fan.values():
                if isinstance(cmd, str):
                    try:
                        return (ir_codec.decode_broadlink_b64(cmd) if enc == "base64"
                                else ir_codec.raw_to_ticks(cmd))
                    except Exception:
                        return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 2: Smoke-test the CLI wiring (no hardware)**

Run: `~/.pyenv/versions/homeautomation/bin/python -m scripts.find_ir_codeset --help`
Expected: argparse usage prints with all flags; no import errors.

- [x] **Step 3: Re-run the full unit suite**

Run: `~/.pyenv/versions/homeautomation/bin/python -m pytest tests/ -v`
Expected: all tests from Tasks 2-7 still PASS (no regressions).

- [x] **Step 4: Commit**

```bash
git add scripts/find_ir_codeset.py
git commit -m "feat(ir): orchestrator — capture, match, disambiguate, replay-confirm, report"
```

---

### Task 10: Hardware verification + docs

**Files:**
- Modify: `docs/state-of-world.md`

- [x] **Step 1: Live test in Dana's office**

Run (Mac, on the LAN; the AC powered ON so OFF is observable):
```bash
~/.pyenv/versions/homeautomation/bin/python scripts/find_ir_codeset.py \
  --device-ip 192.168.1.19 --controller remote.danaofficeremote
```
Expected: prompts for OFF ×3 → prints a ranked shortlist → replays the top candidate → on "y", prints the `MATCH` report with manufacturer/model/device_code.

- [x] **Step 2: Confirm in HA**

In Home Assistant, add `ar_smart_ir` → Climate → pick the reported manufacturer/model (device_code), controller `remote.danaofficeremote`. Verify the AC responds to a climate command.

- [x] **Step 3: Repeat for the master/main AC**

Run with the living-room RM4 Pro:
```bash
~/.pyenv/versions/homeautomation/bin/python scripts/find_ir_codeset.py \
  --device-ip 192.168.1.18 --controller remote.broadlink_main_ac_and_fans
```

- [x] **Step 4: Mark backlog item #2 done**

In `docs/state-of-world.md`, update Section 7 item 2 (IR code-set finder script) to note it is implemented (`scripts/find_ir_codeset.py`), keeping the remaining "main-AC IR codes" hookup as the open follow-up.

- [x] **Step 5: Commit**

```bash
git add docs/state-of-world.md
git commit -m "docs: IR code-set finder implemented; mark backlog #2"
```

---

## Self-Review

**Spec coverage:**
- Hybrid match (signal + replay-confirm) → Tasks 5, 6, 9. ✓
- `off` ×3 → median, adaptive 2nd command → Tasks 7, 9. ✓
- Manual UI config (report only) → Task 7 `format_report` + Task 9 report block. ✓
- Standalone, IPs as flags, no repo coupling → Task 9 argparse (`--device-ip`/`--discover`). ✓
- DB into `/tmp`, clone/`--refresh-db`, no version pin → Task 8 `ensure_db`. ✓
- mini-DB cache, jq-parallel + Python fallback, shortlist-only full reads → Task 8 `build_mini_db`, Task 9 `_load_full_codeset`. ✓
- climate-only scope → DB glob `codes/climate`. ✓
- Base64 + Raw handling → Tasks 2, 4, 5. ✓
- Error handling (no device, timeout, inconsistent captures, missing off, raw) → Tasks 7, 9. ✓
- Testing (codec fixtures, match scoring, pure helpers; hardware excluded) → Tasks 2-7, 10. ✓

**Placeholder scan:** `--controller` default `remote.<your_broadlink_entity>` is an intentional CLI placeholder overridden by the real entity in Task 10; the `_extract_cool_command` walk is best-effort by design (returns None when absent). No TBD/TODO steps.

**Type consistency:** `decode_broadlink_b64`, `encode_broadlink`, `raw_to_ticks`, `b64_to_bytes` (codec); `score`, `entry_to_ticks`, `load_mini_db`, `rank`, `is_tie` (match); `clean_captures`, `format_report`, `ensure_db`, `build_mini_db`, `connect_device`, `capture`, `replay`, `main` (orchestrator) — names and signatures consistent across tasks. Mini-DB row keys (`device_code`, `manufacturer`, `models`, `enc`, `off`) identical in Task 8 build and Task 5/6 consumers.
