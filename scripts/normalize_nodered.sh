#!/usr/bin/env bash
# Normalize a Node-RED flow JSON for clean git diffs:
#  - drop volatile canvas coordinates (x, y) and editor-only fields
#  - sort object keys deterministically
# Usage: normalize_nodered.sh <file>   (prints normalized JSON to stdout)
set -euo pipefail
file="${1:?usage: normalize_nodered.sh <flow.json>}"
jq -S 'walk(if type == "object" then del(.x, .y) else . end) | sort_by(.id)' "$file"
