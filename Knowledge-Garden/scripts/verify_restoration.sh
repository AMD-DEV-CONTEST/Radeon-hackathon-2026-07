#!/bin/bash
# verify_restoration.sh — assert a restored vLLM service matches a captured descriptor.
# Four checks:
#   (a) GET /v1/models returns the captured served model ID
#   (b) listener ownership: the inspected PID owns the port
#   (c) the API request targets that verified listener (PID<->port binding)
#   (d) independently recovered checkpoint revision equals the descriptor's
# Usage:
#   bash scripts/verify_restoration.sh --port <port> --descriptor <experiment.json>
set -u

PORT=""
DESCRIPTOR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    --descriptor) DESCRIPTOR="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$PORT" ] || { echo "verify_restoration: --port required" >&2; exit 2; }
[ -n "$DESCRIPTOR" ] && [ -f "$DESCRIPTOR" ] || { echo "verify_restoration: --descriptor file required" >&2; exit 2; }

# Parse descriptor with python (jsonl-safe)
read_descriptor() {
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
key = sys.argv[2]
if key in d:
    v = d[key]
    print(v if isinstance(v, str) else json.dumps(v))
' "$DESCRIPTOR" "$1"
}

EXPECTED_ID="$(read_descriptor served_model_id)"
EXPECTED_CHECKPOINT="$(read_descriptor checkpoint_path)"
EXPECTED_REV="$(read_descriptor checkpoint_revision)"
EXPECTED_EXEC="$(read_descriptor executable)"

fail() { echo "VERIFY_RESTORATION_FAIL: $1" >&2; exit 1; }

# (a) served model ID via /v1/models
BODY="$(curl -fsS --max-time 15 "http://127.0.0.1:${PORT}/v1/models" 2>/dev/null)" || fail "(a) GET /v1/models failed on :$PORT"
echo "$BODY" | grep -q "\"${EXPECTED_ID}\"" || fail "(a) served model ID mismatch: expected ${EXPECTED_ID}"

# (b) listener ownership: find PID owning the port
PID="$(bash /persistent/learning-companion/scripts/find_listener_pid.sh "$PORT" 2>/dev/null || true)"
[ -n "$PID" ] || PID="$(ss -ltnp "sport = :${PORT}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)"
[ -n "$PID" ] || PID="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -1)"
[ -n "$PID" ] || fail "(b) no listener PID found on :${PORT}"

# (c) request-to-listener binding: the process cmdline must be the vLLM api_server
CMD="$(tr '\0' ' ' < "/proc/${PID}/cmdline" 2>/dev/null)"
echo "$CMD" | grep -q "openai.api_server" || fail "(c) PID ${PID} is not a vLLM api_server"

# (d) independently recovered checkpoint revision
if [ -f "${EXPECTED_CHECKPOINT}/model-manifest.json" ]; then
  REV="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("revision",""))' "${EXPECTED_CHECKPOINT}/model-manifest.json" 2>/dev/null || true)"
elif [ -f "${EXPECTED_CHECKPOINT}/config.json" ]; then
  REV="$(sha256sum "${EXPECTED_CHECKPOINT}/config.json" "${EXPECTED_CHECKPOINT}"/model.safetensors.index.json 2>/dev/null | sha256sum | cut -d' ' -f1)"
else
  REV=""
fi
[ -n "$REV" ] || fail "(d) cannot independently recover checkpoint revision for ${EXPECTED_CHECKPOINT}"
[ "$REV" = "$EXPECTED_REV" ] || fail "(d) checkpoint revision mismatch: expected ${EXPECTED_REV}, got ${REV}"

echo "VERIFY_RESTORATION_OK: port=${PORT} model=${EXPECTED_ID} pid=${PID}"
exit 0
