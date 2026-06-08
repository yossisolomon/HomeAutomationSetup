#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
out="$(bash "$ROOT/scripts/normalize_nodered.sh" "$ROOT/tests/fixtures/flow_raw.json")"
expected="$(cat "$ROOT/tests/fixtures/flow_expected.json")"
# Compare canonically with jq -S so whitespace/ordering is irrelevant.
if diff <(echo "$out" | jq -S .) <(echo "$expected" | jq -S .) >/dev/null; then
  echo "PASS"
else
  echo "FAIL: normalizer output != expected"; echo "$out" | jq -S .; exit 1
fi
