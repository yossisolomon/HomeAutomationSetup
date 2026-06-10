# HACS Plugin Tracking Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop vendoring HACS plugin code in git; track a generated `hacs-manifest.yaml` instead, and document a HACS-managed rebuild restore.

**Architecture:** A pure-Python generator (`scripts/gen_hacs_manifest.py`) reads HACS's install record (`.storage/hacs.repositories`, blacky-only, root-owned) and emits a deterministic `hacs-manifest.yaml` at the repo root. The plugin code dirs under `config/custom_components/*/` are gitignored and untracked. A rebuild runbook lives in the manifest header and `docs/state-of-world.md`.

**Tech Stack:** Python 3.11 (pyenv `homeautomation`), pytest, stdlib only (`json`, `argparse`, `pathlib`, `os`, `tempfile`). YAML is emitted by hand (no PyYAML dependency) for full control of the header comment and stable diffs.

---

## Context the implementer needs

- **Repo:** `/Users/yossi_solomon/dev/HomeAutomationSetup` on `main`. Commits are
  pre-approved per project workflow; commit directly on `main` (this is how the prior
  IR-finder work landed). A `pre-commit` hook regenerates `docs/automations.md` — let
  it run; it is not related to this work.
- **Tests run on the Mac** in the pyenv `homeautomation` virtualenv:
  `source $(pyenv prefix homeautomation)/bin/activate && python -m pytest <path> -v`.
  The working directory is the repo root.
- **Existing test layout:** `tests/test_*.py`, fixtures in `tests/fixtures/`. Follow
  the style of `tests/test_find_ir_codeset.py` (plain `pytest`, `from scripts import
  <module> as f`). `tests/__init__.py` exists so `scripts` imports resolve.
- **The actual HACS store shape** (verified on blacky): top-level JSON is
  `{"version": ..., "key": "hacs.repositories", "data": [ {repo}, {repo}, ... ]}`.
  Each repo dict has the keys: `full_name`, `domain`, `category`, `installed`
  (bool), `version_installed` (release tag string, may be empty/null), and
  `installed_commit` (SHA string). 5 repos are installed; ~3100 are not.
- **Tasks 1–3 are pure Python + unit tests (Mac).** Tasks 4–6 are operational
  (run on blacky / edit docs) and use explicit verification commands instead of
  unit tests.

## File structure

- `scripts/gen_hacs_manifest.py` (new) — generator. Pure functions for load/extract/
  render/path-resolution, plus a thin `main()` for CLI + I/O + error handling.
- `tests/test_gen_hacs_manifest.py` (new) — unit tests.
- `tests/fixtures/hacs_repositories_sample.json` (new) — trimmed store fixture.
- `hacs-manifest.yaml` (new, generated on blacky in Task 4).
- `.gitignore` (modify) — ignore plugin dirs.
- `docs/state-of-world.md` (modify) — mark backlog #11 done + link runbook.
- `README.md` (modify) — short pointer to the manifest + regenerate command.

---

### Task 1: Generator module scaffold + store loading

**Files:**
- Create: `scripts/gen_hacs_manifest.py`
- Create: `tests/fixtures/hacs_repositories_sample.json`
- Create: `tests/test_gen_hacs_manifest.py`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/hacs_repositories_sample.json` with two installed repos (one
with a release tag, one branch-only so it has no `version_installed`) and one
not-installed repo:

```json
{
  "version": 1,
  "key": "hacs.repositories",
  "data": [
    {
      "full_name": "rospogrigio/localtuya",
      "domain": "localtuya",
      "category": "integration",
      "installed": true,
      "version_installed": "2025.5.0",
      "installed_commit": "aaaaaaa"
    },
    {
      "full_name": "marsh4200/ar_smart_ir",
      "domain": "ar_smart_ir",
      "category": "integration",
      "installed": true,
      "version_installed": null,
      "installed_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    },
    {
      "full_name": "some/not-installed",
      "domain": "noop",
      "category": "integration",
      "installed": false,
      "version_installed": null,
      "installed_commit": "ccccccc"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test for `load_store`**

Create `tests/test_gen_hacs_manifest.py`:

```python
import os

import pytest
from scripts import gen_hacs_manifest as f

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "hacs_repositories_sample.json")


def test_load_store_returns_repo_list():
    rows = f.load_store(FIXTURE)
    assert isinstance(rows, list)
    assert len(rows) == 3
    assert any(r["full_name"] == "marsh4200/ar_smart_ir" for r in rows)


def test_load_store_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        f.load_store("/no/such/hacs.repositories")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `source $(pyenv prefix homeautomation)/bin/activate && python -m pytest tests/test_gen_hacs_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.gen_hacs_manifest'`.

- [ ] **Step 4: Implement the module scaffold + `load_store`**

Create `scripts/gen_hacs_manifest.py`:

```python
"""Generate hacs-manifest.yaml from HACS's install record (.storage/hacs.repositories).

Runs on blacky (the only host with the store). Pure transform + a thin CLI.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

GITHUB = "https://github.com/"


def load_store(path: str) -> list[dict]:
    """Return the list of repo dicts from a HACS .storage/hacs.repositories file.

    The HA store wraps the payload as {"data": [...]}; tolerate a bare list/dict too.
    Raises FileNotFoundError if absent, ValueError if the JSON is malformed.
    """
    with open(path, encoding="utf-8") as fh:
        try:
            doc = json.load(fh)
        except json.JSONDecodeError as err:
            raise ValueError(f"malformed HACS store at {path}: {err}") from err
    data = doc.get("data", doc) if isinstance(doc, dict) else doc
    if isinstance(data, dict):
        return list(data.values())
    return list(data)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `source $(pyenv prefix homeautomation)/bin/activate && python -m pytest tests/test_gen_hacs_manifest.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add scripts/gen_hacs_manifest.py tests/test_gen_hacs_manifest.py tests/fixtures/hacs_repositories_sample.json
git commit -m "feat(hacs): gen_hacs_manifest store loader + fixture"
```

---

### Task 2: Extract installed plugins into normalized records

**Files:**
- Modify: `scripts/gen_hacs_manifest.py`
- Test: `tests/test_gen_hacs_manifest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gen_hacs_manifest.py`:

```python
def test_installed_plugins_filters_and_normalizes():
    rows = f.load_store(FIXTURE)
    plugins = f.installed_plugins(rows)
    names = [p["full_name"] for p in plugins]
    # only installed, sorted by full_name
    assert names == ["marsh4200/ar_smart_ir", "rospogrigio/localtuya"]


def test_installed_plugins_version_pin_tag_then_commit():
    plugins = {p["full_name"]: p for p in f.installed_plugins(f.load_store(FIXTURE))}
    assert plugins["rospogrigio/localtuya"]["version"] == "2025.5.0"
    assert plugins["marsh4200/ar_smart_ir"]["version"] == \
        "commit:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_installed_plugins_defaults_source_and_derives_repo():
    p = f.installed_plugins(f.load_store(FIXTURE))[0]
    assert p["source"] == "custom-repo"
    assert p["repo"] == "https://github.com/marsh4200/ar_smart_ir"
    assert p["category"] == "integration"
    assert p["domain"] == "ar_smart_ir"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source $(pyenv prefix homeautomation)/bin/activate && python -m pytest tests/test_gen_hacs_manifest.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'installed_plugins'`.

- [ ] **Step 3: Implement `installed_plugins`**

Add to `scripts/gen_hacs_manifest.py`:

```python
def _pin(repo: dict) -> str:
    tag = repo.get("version_installed")
    if tag:
        return str(tag)
    return f"commit:{repo.get('installed_commit', '')}"


def installed_plugins(rows: list[dict]) -> list[dict]:
    """Filter to installed repos and normalize to manifest records, sorted by name.

    `source` defaults to "custom-repo" (the always-works restore path) because
    default-store membership can't be determined offline; a human may correct it.
    """
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if not (r.get("installed") or r.get("version_installed")):
            continue
        full = r.get("full_name", "")
        out.append({
            "full_name": full,
            "domain": r.get("domain", ""),
            "category": r.get("category", ""),
            "version": _pin(r),
            "source": "custom-repo",
            "repo": GITHUB + full,
        })
    out.sort(key=lambda p: p["full_name"])
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source $(pyenv prefix homeautomation)/bin/activate && python -m pytest tests/test_gen_hacs_manifest.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/gen_hacs_manifest.py tests/test_gen_hacs_manifest.py
git commit -m "feat(hacs): extract+normalize installed plugins"
```

---

### Task 3: Render YAML, resolve storage path, CLI `main()`

**Files:**
- Modify: `scripts/gen_hacs_manifest.py`
- Test: `tests/test_gen_hacs_manifest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gen_hacs_manifest.py`:

```python
def test_render_manifest_has_runbook_and_entries():
    plugins = f.installed_plugins(f.load_store(FIXTURE))
    text = f.render_manifest(plugins)
    assert "REBUILD RUNBOOK" in text
    assert "plugins:" in text
    assert "full_name: marsh4200/ar_smart_ir" in text
    assert "version: commit:bbbbbbbb" in text  # commit pins are quoted-safe bare
    assert "version: 2025.5.0" in text
    # deterministic ordering: ar_smart_ir entry precedes localtuya entry
    assert text.index("marsh4200/ar_smart_ir") < text.index("rospogrigio/localtuya")


def test_resolve_storage_prefers_explicit():
    assert f.resolve_storage_path("/x/y", env={}) == "/x/y"


def test_resolve_storage_uses_sudo_user():
    got = f.resolve_storage_path(None, env={"SUDO_USER": "yossi"})
    assert got == "/home/yossi/homeassistant/config/.storage/hacs.repositories"


def test_main_writes_manifest(tmp_path):
    out = tmp_path / "hacs-manifest.yaml"
    rc = f.main(["--storage", FIXTURE, "--out", str(out)])
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "marsh4200/ar_smart_ir" in body and "rospogrigio/localtuya" in body


def test_main_zero_installed_is_error(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text('{"data": []}', encoding="utf-8")
    out = tmp_path / "m.yaml"
    rc = f.main(["--storage", str(empty), "--out", str(out)])
    assert rc != 0
    assert not out.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source $(pyenv prefix homeautomation)/bin/activate && python -m pytest tests/test_gen_hacs_manifest.py -v`
Expected: FAIL — `AttributeError: ... 'render_manifest'`.

- [ ] **Step 3: Implement rendering, path resolution, and `main()`**

Add to `scripts/gen_hacs_manifest.py`:

```python
HEADER = """\
# HACS plugin manifest — generated by scripts/gen_hacs_manifest.py on blacky.
# Do not hand-edit. Regenerate after installing/updating a HACS plugin, then commit:
#   sudo python3 scripts/gen_hacs_manifest.py
#
# REBUILD RUNBOOK (HACS-managed restore):
#   1. Install HACS (hacs/integration) per the official docs; restart HA.
#   2. For each plugin below:
#        - source: custom-repo   -> HACS > (⋮) Custom repositories: add `repo` with
#                                    the listed `category`, then install at `version`.
#        - source: default-store -> search `full_name` in HACS, install at `version`.
#   3. Restart HA. Re-link config entries — tokens/pairings live in .storage, not git.
"""


def render_manifest(plugins: list[dict]) -> str:
    lines = [HEADER, "plugins:"]
    for p in plugins:
        lines.append(f"  - full_name: {p['full_name']}")
        lines.append(f"    domain: {p['domain']}")
        lines.append(f"    category: {p['category']}")
        lines.append(f"    version: {p['version']}")
        lines.append(f"    source: {p['source']}")
        lines.append(f"    repo: {p['repo']}")
    return "\n".join(lines) + "\n"


def resolve_storage_path(explicit: str | None, env=None) -> str:
    env = os.environ if env is None else env
    if explicit:
        return explicit
    user = env.get("SUDO_USER")
    if user:
        return f"/home/{user}/homeassistant/config/.storage/hacs.repositories"
    return str(Path.home() / "homeassistant/config/.storage/hacs.repositories")


def _default_out() -> str:
    return str(Path(__file__).resolve().parents[1] / "hacs-manifest.yaml")


def _write_atomic(text: str, out_path: str) -> None:
    out = Path(out_path)
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, out_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Generate hacs-manifest.yaml from HACS's store.")
    p.add_argument("--storage", default=None, help="path to .storage/hacs.repositories")
    p.add_argument("--out", default=None, help="manifest output path")
    args = p.parse_args(argv)

    storage = resolve_storage_path(args.storage)
    out = args.out or _default_out()
    try:
        rows = load_store(storage)
    except FileNotFoundError:
        print(f"HACS store not found: {storage}\n"
              f"Run on blacky with sudo, or pass --storage.", file=sys.stderr)
        return 2
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 2

    plugins = installed_plugins(rows)
    if not plugins:
        print(f"No installed plugins found in {storage} — wrong path?", file=sys.stderr)
        return 1

    _write_atomic(render_manifest(plugins), out)
    print(f"Wrote {out} with {len(plugins)} plugins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full test file to verify it passes**

Run: `source $(pyenv prefix homeautomation)/bin/activate && python -m pytest tests/test_gen_hacs_manifest.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/gen_hacs_manifest.py tests/test_gen_hacs_manifest.py
git commit -m "feat(hacs): render manifest YAML + CLI main"
```

---

### Task 4: Generate the real manifest on blacky and commit it

**Files:**
- Create: `hacs-manifest.yaml` (generated)

This task runs commands against blacky; there is no unit test. `scripts/` is synced to
blacky's `~/homeassistant/scripts/` (same path the IR finder runs from).

- [ ] **Step 1: Copy the generator to blacky**

```bash
scp /Users/yossi_solomon/dev/HomeAutomationSetup/scripts/gen_hacs_manifest.py blacky:~/homeassistant/scripts/gen_hacs_manifest.py
```

- [ ] **Step 2: Run the generator on blacky, writing to /tmp first (verify before trusting)**

```bash
ssh blacky 'cd ~/homeassistant && sudo python3 scripts/gen_hacs_manifest.py --out /tmp/hacs-manifest.yaml && cat /tmp/hacs-manifest.yaml'
```
Expected: prints `Wrote /tmp/hacs-manifest.yaml with 5 plugins.` then a YAML doc whose
`plugins:` list contains `hacs/integration`, `rospogrigio/localtuya`,
`mash2k3/qingping_cgs1`, `marsh4200/ar_smart_ir`, `XiaoMi/ha_xiaomi_home`, each with a
`version:` that is either a tag or `commit:<sha>`.

- [ ] **Step 3: Bring the manifest to the Mac repo**

```bash
scp blacky:/tmp/hacs-manifest.yaml /Users/yossi_solomon/dev/HomeAutomationSetup/hacs-manifest.yaml
```

- [ ] **Step 4: Eyeball + correct `source` flags**

Open `hacs-manifest.yaml`. The generator marks every plugin `source: custom-repo`.
`hacs/integration` is the bootstrap (installed via the HACS install script, not the
UI) — leave it `custom-repo` (the runbook step 1 covers it). Plugins that you know are
in the HACS default store may be changed to `source: default-store`; if unsure, leave
`custom-repo` (it always works). This is the one human edit allowed on the file.

- [ ] **Step 5: Commit the manifest**

```bash
git add hacs-manifest.yaml
git commit -m "feat(hacs): add generated hacs-manifest.yaml (5 plugins)"
```

---

### Task 5: Untrack plugin dirs + gitignore them

**Files:**
- Modify: `.gitignore`
- Removes from index (not disk): `config/custom_components/<tracked dirs>`

Runs against the **blacky** checkout, because that is where the plugin files live and
where git tracks them (the Mac repo may not contain `config/custom_components/` at
all). Verify first whether these commands should run on blacky or Mac:

- [ ] **Step 1: Confirm where the plugin dirs are tracked**

```bash
git -C /Users/yossi_solomon/dev/HomeAutomationSetup ls-files config/custom_components/ | head -1
ssh blacky 'git -C ~/homeassistant ls-files config/custom_components/ | head -1'
```
Whichever checkout returns a path is the one to run Steps 2–4 against. Expected: the
blacky checkout lists files (e.g. `config/custom_components/hacs/__init__.py`). If the
Mac repo also lists them, perform the steps in **both** checkouts.

- [ ] **Step 2: Add the gitignore rule (in the repo where you commit — Mac)**

Append to `/Users/yossi_solomon/dev/HomeAutomationSetup/.gitignore`:

```gitignore
# HACS-installed plugins — tracked via hacs-manifest.yaml, not vendored.
config/custom_components/*/
```

- [ ] **Step 3: Untrack the vendored plugin dirs (on the checkout from Step 1)**

On the checkout that tracks them (blacky shown here; mirror on Mac if needed):

```bash
ssh blacky 'cd ~/homeassistant && git rm -r --cached --quiet config/custom_components/hacs config/custom_components/localtuya config/custom_components/xiaomi_home && echo "untracked $(git status --porcelain config/custom_components | grep -c "^D") dirs of files"'
```
Expected: a count > 0; files remain on disk (`ls config/custom_components/hacs` still
works).

- [ ] **Step 4: Verify ignore + that HA still has the files**

```bash
ssh blacky 'cd ~/homeassistant && git check-ignore config/custom_components/ar_smart_ir/climate.py && test -f config/custom_components/ar_smart_ir/climate.py && echo "ignored-and-present OK"'
git -C /Users/yossi_solomon/dev/HomeAutomationSetup check-ignore config/custom_components/hacs/__init__.py && echo "mac-ignore OK"
```
Expected: both echo their OK lines.

- [ ] **Step 5: Commit (Mac for `.gitignore`; blacky for the index removal)**

```bash
# Mac: the gitignore rule
git -C /Users/yossi_solomon/dev/HomeAutomationSetup add .gitignore
git -C /Users/yossi_solomon/dev/HomeAutomationSetup commit -m "chore(hacs): gitignore vendored plugin dirs"
# blacky: the index removal (if blacky tracked them)
ssh blacky 'cd ~/homeassistant && git commit -q -m "chore(hacs): untrack vendored plugin dirs" && echo committed'
```

---

### Task 6: Runbook docs + mark backlog #11 done

**Files:**
- Modify: `README.md`
- Modify: `docs/state-of-world.md`

- [ ] **Step 1: Add a README pointer**

Add a short section to `README.md` (near any existing setup/scripts notes):

```markdown
## HACS plugins

HACS-installed integrations are **not** vendored in git. The installed set and pinned
versions are recorded in [`hacs-manifest.yaml`](hacs-manifest.yaml); its header has the
rebuild runbook. Regenerate after installing/updating a plugin (on blacky):

```bash
sudo python3 scripts/gen_hacs_manifest.py
```
```

- [ ] **Step 2: Update backlog #11 in `docs/state-of-world.md`**

Find backlog item 11 (the "Reconcile blacky git drift" entry) and replace its
`ar_smart_ir` / `qingping_cgs1` untracked clause with a done note:

```markdown
11. **Reconcile blacky git drift** *(part of #10)* — live config on blacky is not fully in
    git: `zigbee2mqtt/config/configuration.yaml` is tracked but has uncommitted local edits.
    ✅ HACS components resolved: all `config/custom_components/*/` plugin dirs are now
    gitignored and tracked via `hacs-manifest.yaml` (see
    [HACS plugin tracking spec](superpowers/specs/2026-06-09-hacs-plugin-tracking-design.md)).
    Remaining: commit the z2m edit.
```

- [ ] **Step 3: Verify the docs reference resolves**

```bash
test -f /Users/yossi_solomon/dev/HomeAutomationSetup/hacs-manifest.yaml && \
  grep -q "hacs-manifest.yaml" /Users/yossi_solomon/dev/HomeAutomationSetup/README.md && \
  echo "docs OK"
```
Expected: `docs OK`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/state-of-world.md
git commit -m "docs(hacs): manifest runbook + mark backlog #11 done"
```

---

## Self-Review

**Spec coverage:**
- Policy & scope (manifest-only, gitignore, .storage out of scope) → Tasks 5, 6 + spec.
- Manifest format/fields/header runbook → Task 3 (`render_manifest`, `HEADER`), Task 4.
- Generator on blacky, sudo path, atomic write, error handling, zero-guard → Tasks 1–3
  (`load_store`, `resolve_storage_path`, `_write_atomic`, `main`).
- Untrack + gitignore cleanup → Task 5.
- Rebuild runbook (HACS-managed) → Task 3 `HEADER` + Task 6 README/state-of-world.
- Verification items from spec → Tasks 3 (unit), 4 (5 entries), 5 (untracked+present).
- Out-of-scope items → left untouched; #11 sibling (z2m edit) explicitly noted as remaining.

**Placeholder scan:** No TBD/TODO; every code step has complete code; every ops step has
exact commands + expected output. The one human judgement (source flags) is bounded with
a safe default.

**Type consistency:** `load_store` → `list[dict]`; `installed_plugins(rows)` consumes that
list and returns records with keys `full_name/domain/category/version/source/repo`;
`render_manifest(plugins)` consumes those same keys; `main` chains
`resolve_storage_path → load_store → installed_plugins → render_manifest → _write_atomic`.
Names consistent across tasks.
