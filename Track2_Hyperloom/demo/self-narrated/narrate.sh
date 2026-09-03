#!/usr/bin/env bash
# narrate.sh — local TTS narration on the AMD Radeon R9700 via Lemonade kokoro-v1.
# No cloud: kokoro (82M, Apache-2.0, ONNX) runs on the card. Proven: an 11.6s clip
# renders to a valid 24kHz MP3. Usage: narrate.sh "<text>" <out.mp3> [voice]
set -euo pipefail
TEXT="${1:?usage: narrate.sh <text> <out.mp3> [voice]}"
OUT="${2:?usage: narrate.sh <text> <out.mp3> [voice]}"
VOICE="${3:-af_sky}"
URL="${LEMONADE_URL:-http://localhost:13305}"
# ensure kokoro is loaded (idempotent)
curl -s -X POST "$URL/api/v1/load" -H 'Content-Type: application/json' \
     -d '{"model_name":"kokoro-v1"}' >/dev/null 2>&1 || true
body="$(python3 -c 'import json,sys;print(json.dumps({"model":"kokoro-v1","input":sys.argv[1],"voice":sys.argv[2]}))' "$TEXT" "$VOICE")"
curl -s -X POST "$URL/api/v1/audio/speech" -H 'Content-Type: application/json' -d "$body" -o "$OUT"
sz="$(stat -c%s "$OUT" 2>/dev/null || echo 0)"
[ "$sz" -gt 1000 ] || { echo "narrate: TTS returned no audio ($(head -c200 "$OUT"))" >&2; exit 1; }
echo "wrote $OUT ($sz bytes)"
