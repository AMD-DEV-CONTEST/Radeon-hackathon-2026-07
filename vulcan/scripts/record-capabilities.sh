#!/usr/bin/env bash
# Record the second demo segment against the local backend.
#
#   bash scripts/record-capabilities.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v vhs >/dev/null || { echo "FAILED: vhs missing. brew install vhs" >&2; exit 1; }
vhs scripts/capabilities.tape
# vhs writes the moov atom last, so existence is not the completion signal.
ffprobe -v error -show_entries format=duration -of csv=p=0 capabilities-raw.mp4
