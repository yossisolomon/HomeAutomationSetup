# Spec — IR Code-Set Finder

> Status: **Approved** (2026-06-09). Brainstormed. Next: implementation plan via writing-plans.
> Backlog item #2 (IR code-set finder script) from `docs/state-of-world.md`.

## Context

ACs are controlled via the `ar_smart_ir` HACS integration (`github.com/marsh4200/ar_smart_ir`,
SmartIR-style fork). It ships **363 climate code-sets** under `codes/climate/<device_code>.json`,
selected in its config flow by **manufacturer → model → device_code**. It already supports
per-command IR learning via a broadlink entity. It has **no code-set finder** — nothing
identifies *which* device_code matches an unknown AC.

The apartment's ACs are Tornado (Israeli rebadge — often not listed under "Tornado" in the DB),
so brand-pick is unreliable. The finder captures the real remote's IR signal and identifies the
matching code-set, so configuration is a single informed UI pick instead of trial-and-error or
learning every command by hand.

A 2nd broadlink — **RM4 mini "DanaOfficeRemote"** (IR-only, `192.168.1.19`) — is now hooked up in
Dana's office. The finder flow is tested there first, then used for the master/main AC.

### Decisions locked (brainstorming)
- **Match approach = hybrid (C):** signal-match the real remote against the DB → ranked
  shortlist, then **replay-confirm** the top candidate on the real AC.
- **Fingerprint = `off` ×3 → median reference**, adaptive 2nd command only on ties/low score.
- **Config creation = manual UI** (script reports manufacturer/model/device_code + controller
  entity; user does the one-off config-flow pick). Auto-creating the HA config entry is rejected
  (fragile storage edits / brittle flow-driving; device_code is only one of several config fields).
- **Standalone + reusable:** all IPs are flags (no hardcoded addresses, no coupling to this
  repo's `fans.json`/blacky/apartment). Deps: `python-broadlink` + stdlib; `jq` optional.
- **DB sourced on demand into `/tmp`** (not in the repo), fetched/refreshed by the orchestrator.
- **Scope = climate code-sets only.** Fans are handled via RF; media_player is out of scope.

### Verified ground truth (de-risked during brainstorming)
- DB packets are standard **broadlink IR**: byte0 `0x26`, byte1 repeat, bytes2-3 LE payload length,
  then a pulse-tick stream (1 byte/pulse, or `0x00` + 2-byte BE for >255), trailer `0x000d…`.
  1 tick ≈ 30.5 µs (2⁻¹⁵ s). Decoding `codes/climate/1000.json` `off` yields 140 pulses starting
  `297,145,…` = 9 ms / 4.5 ms leader (NEC-family). Capture and DB share the same tick unit →
  comparison is done directly in tick-space, no absolute-time conversion needed.
- Encodings across the 363 sets: ~339 **Base64**, ~24 **Raw** (SmartIR Raw = µs integer list →
  converted to ticks via `round(µs / 30.5176)` for comparison).
- IR capture API differs from RF only at the entry call: IR uses `dev.enter_learning()`
  (single phase); RF uses `dev.find_rf_packet(freq)` (needs frequency). Both then poll
  `dev.check_data()` and decode identically.

---

## Architecture

A self-contained trio under `scripts/` — depends only on `python-broadlink` + stdlib (jq optional),
no imports from the rest of the repo:

- **`scripts/find_ir_codeset.py`** — CLI orchestrator: DB fetch → capture → clean → match → rank →
  disambiguate → replay-confirm → report.
- **`scripts/ir_codec.py`** — pure functions: broadlink IR ↔ pulse-tick array (decode Base64,
  parse Raw µs→ticks, re-encode ticks→Base64 for replay). Unit-tested, no I/O.
- **`scripts/ir_match.py`** — pure functions: mini-DB load + similarity scoring + ranking.
  Unit-tested, no hardware.

### DB sourcing (orchestrator, into `/tmp`)
- Default `--db-dir /tmp/ar_smart_ir_db` (overridable).
- **Present** → use it. **Missing** →
  `git clone --filter=blob:none --sparse github.com/marsh4200/ar_smart_ir <db-dir>` then
  `git -C <db-dir> sparse-checkout set codes`. **`--refresh-db`** → `git -C <db-dir> pull`
  (latest commit; no version pin).
- After clone/refresh, build a **mini-DB cache** `<db-dir>/mini_db.ndjson` — one compact JSON
  object per code-set with just what phase-1 matching needs:
  `{device_code, manufacturer, models, enc, off}`. `device_code` = filename stem.
  - Built in parallel with **jq** when available:
    ```bash
    find <db-dir>/codes/climate -name '*.json' -print0 \
      | xargs -0 -P"$(nproc)" -I{} jq -c \
        '{device_code:(input_filename|gsub(".*/";"")|gsub(".json$";"")), manufacturer, models:.supportedModels, enc:.commandsEncoding, off:.commands.off}' {} \
      > <db-dir>/mini_db.ndjson
    ```
  - **Pure-Python fallback** when jq is absent (keeps the tool standalone).
  - Rebuilt only when the clone changes or `--refresh-db` is passed; otherwise the cache loads
    near-instantly (avoids parsing 363 full files every run).
- The adaptive 2nd command reads the **full JSON only for the top-N shortlist** (a handful of
  files), never the whole DB.

### Broadlink device (flags, no hardcoding)
- `--device-ip <ip>` **required**, or `--discover` to scan via `broadlink.discover()`.
- Optional `--device-mac` / `--timeout`. Connect via `broadlink.hello(ip)` + `dev.auth()`.

## Data flow

1. **Capture** — `dev.enter_learning()`, poll `dev.check_data()` until a packet arrives or timeout;
   prompt "press OFF". Repeat **×3** (configurable `--captures`).
2. **Clean** — `ir_codec` decodes each capture to a tick array. Drop captures whose pulse count
   differs from the modal count; per-pulse **median** of the survivors → reference. If the
   captures disagree wildly (e.g. <2 share a pulse count), warn and re-prompt (bad reception /
   wrong button) rather than match noise.
3. **Match** — `ir_match` loads `mini_db.ndjson`, decodes each set's `off` (Base64 → ticks, or Raw
   µs → ticks), scores vs the reference: **gate** on pulse-count within ±2, then
   `score = fraction of pulses within ±15% tick tolerance` (0–100%). Rank descending.
4. **Disambiguate (adaptive)** — if the top scores tie (within a small margin) or all are low,
   prompt for a 2nd distinctive command (e.g. cool, fixed temp + fan), capture ×3 → median, read
   that command's path from the **full JSON of the shortlist only**, re-score, intersect rankings.
5. **Replay-confirm** — `ir_codec` re-encodes the top candidate's `off` → `dev.send_data()`; ask
   "did the AC react? [y/N]". On **N**, advance to the next candidate and repeat.
6. **Report** — print the confirmed match:
   ```
   MATCH (94%, replay-confirmed):
     manufacturer : Tornado
     model        : RGS-XYZ
     device_code  : 1234
   → ar_smart_ir → Climate → manufacturer "Tornado" → that model
   → controller entity: remote.danaofficeremote
   ```
   On no confirmed match, print the top-N table (device_code, manufacturer, model, score) for
   manual replay/trial.

## Error handling
- **No device / auth fail** — clear message; suggest `--discover`.
- **Capture timeout** — re-prompt, up to a retry limit; never block forever.
- **Inconsistent captures** — warn + re-prompt (don't match noise).
- **Missing `git`/network on first clone** — fail with the exact clone command to run manually.
- **`off` absent / unparseable in a set** — skip that set, continue (don't abort the whole run).
- **Raw-encoded sets** — converted µs→ticks and matched with the same metric (slightly looser in
  practice; the pulse-count gate still applies).

## Testing (TDD)
- **`ir_codec`** (pure, fixtures committed under `tests/fixtures/`):
  - decode the `1000.json` `off` Base64 → expected 140-pulse array (`297,145,…`).
  - round-trip: `encode(decode(b64)) == b64` (canonical form).
  - Raw parse: µs list → ticks.
- **`ir_match`** (pure):
  - identical reference vs DB packet → 100%.
  - reference with ±10% per-pulse jitter → high score (above tie threshold).
  - different protocol / pulse count → rejected by the gate (low/zero).
  - ranking + tie detection on a small synthetic mini-DB.
- **Hardware steps** (capture / replay) are **not** unit-tested; exercised manually in **Dana's
  office first**, then the master/main AC.

## Files created (this spec)
- `scripts/find_ir_codeset.py` (new) — orchestrator CLI.
- `scripts/ir_codec.py` (new) — broadlink IR codec.
- `scripts/ir_match.py` (new) — mini-DB load + scoring.
- `tests/test_ir_codec.py`, `tests/test_ir_match.py` (new) + `tests/fixtures/` packets.
- `scripts/requirements.txt` — ensure `broadlink` listed (already used by the RF scripts).
- `docs/state-of-world.md` — mark backlog item #2 done when shipped.

## Verification
1. `python3 scripts/find_ir_codeset.py --device-ip 192.168.1.19` in Dana's office → prompts for
   OFF ×3 → prints a ranked match → replay-confirm → reports manufacturer/model/device_code.
2. Enter that device_code in the `ar_smart_ir` config flow → the AC responds to HA climate
   commands.
3. `--refresh-db` re-pulls the DB and rebuilds `mini_db.ndjson`.
4. Unit tests pass: `pytest tests/test_ir_codec.py tests/test_ir_match.py`.
5. Repeat for the master/main AC via the living-room RM4 Pro (`--device-ip 192.168.1.18`).

## Out of scope (own specs if needed)
Auto-creating the HA config entry · media_player / fan finders · modifying the HACS component ·
learning/saving full command sets (the integration already does per-command learning).
