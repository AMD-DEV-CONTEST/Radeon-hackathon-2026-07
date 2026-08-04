#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON="/opt/venv/bin/python"
RC_TUNNEL="${HOME}/.local/bin/rc-tunnel"
PORT="${BRANDPILOT_DEMO_PORT:-8000}"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}/brandpilot-radeon-demo-${UID}"
PID_FILE="${RUNTIME_DIR}/uvicorn.pid"
LOG_FILE="${RUNTIME_DIR}/uvicorn.log"

fail() {
  printf '%s\n' "startup unavailable: $1"
  exit 1
}

[ -n "${PERSISTENT_ROOT:-}" ] && [ -d "$PERSISTENT_ROOT" ] ||
  fail "persistent storage is required"
[ -n "${DEMO_AUTH_TOKEN:-}" ] || fail "temporary authentication is required"
"$PYTHON" - <<'PY' >/dev/null 2>&1 || fail "temporary authentication is invalid"
import os
raise SystemExit(0 if len(os.environ["DEMO_AUTH_TOKEN"].encode()) >= 32 else 1)
PY
[ -x "$RC_TUNNEL" ] || fail "official tunnel is unavailable"
[ "$("$RC_TUNNEL" version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)" = "0.3.0" ] ||
  fail "official tunnel version is unsupported"
printf '%s' "$PORT" | grep -Eq '^[0-9]+$' || fail "selected port is invalid"
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || fail "selected port is invalid"

if ! bash "$SCRIPT_DIR/bootstrap_radeon_runtime.sh" --check-only >/dev/null; then
  bash "$SCRIPT_DIR/bootstrap_radeon_runtime.sh" --install >/dev/null ||
    fail "runtime bootstrap failed"
fi

export APP_MODE="rocm"
export ENABLE_EXPERIMENTAL_ROCM="true"
export DEMO_AUTH_ENABLED="true"
export EXPERIMENTAL_MAX_ACTIVE_JOBS="1"
export MODEL_ID="stabilityai/stable-diffusion-xl-base-1.0"
export MODEL_REVISION="462165984030d82259a11f4367a4eed129e94a7b"
export DEVICE="cuda"
export DTYPE="float16"
export BACKEND_CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"

[ -n "${MODEL_CACHE_DIR:-}" ] && [ -d "$MODEL_CACHE_DIR" ] ||
  fail "verified model cache is required"
export ROCM_OUTPUT_DIR="${ROCM_OUTPUT_DIR:-${PERSISTENT_ROOT%/}/brandpilot-rocm-outputs}"
mkdir -p -- "$ROCM_OUTPUT_DIR" "$RUNTIME_DIR"
chmod 700 "$RUNTIME_DIR"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  fail "demo backend is already active"
fi
if command -v ss >/dev/null 2>&1 &&
  ss -ltn | grep -Eq "127\\.0\\.0\\.1:${PORT}[[:space:]]"; then
  fail "loopback port is already in use"
fi

cd -- "$REPOSITORY_ROOT/backend"
: >"$LOG_FILE"
chmod 600 "$LOG_FILE"
nohup "$PYTHON" -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port "$PORT" \
  >"$LOG_FILE" 2>&1 &
backend_pid=$!
printf '%s\n' "$backend_pid" >"$PID_FILE"
chmod 600 "$PID_FILE"

healthy=false
for _ in $(seq 1 30); do
  if "$PYTHON" - "$PORT" <<'PY' >/dev/null 2>&1
import sys
import urllib.request
with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=1) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
  then
    healthy=true
    break
  fi
  sleep 1
done
[ "$healthy" = true ] || {
  kill "$backend_pid" 2>/dev/null || true
  rm -f -- "$PID_FILE"
  fail "loopback backend did not become healthy"
}

"$PYTHON" - "$PORT" <<'PY' >/dev/null 2>&1 || fail "backend authentication check failed"
import json
import os
import sys
import urllib.error
import urllib.request

base = f"http://127.0.0.1:{sys.argv[1]}"
try:
    urllib.request.urlopen(base + "/experimental/rocm/status", timeout=2)
    raise SystemExit(1)
except urllib.error.HTTPError as exc:
    if exc.code != 401:
        raise
request = urllib.request.Request(
    base + "/experimental/rocm/status",
    headers={"Authorization": "Bearer " + os.environ["DEMO_AUTH_TOKEN"]},
)
with urllib.request.urlopen(request, timeout=4) as response:
    payload = json.load(response)
if not (
    payload.get("enabled")
    and payload.get("gpu_connected")
    and payload.get("rocm_available")
    and payload.get("model_loaded") is False
    and payload.get("model_id") == "stabilityai/stable-diffusion-xl-base-1.0"
    and payload.get("model_revision") == "462165984030d82259a11f4367a4eed129e94a7b"
):
    raise SystemExit(1)
PY

"$RC_TUNNEL" expose --port "$PORT" >/dev/null ||
  fail "official tunnel did not start"
"$RC_TUNNEL" status >/dev/null 2>&1 ||
  fail "official tunnel status is unavailable"

printf '%s\n' "loopback backend: available"
printf '%s\n' "backend authentication: available"
printf '%s\n' "official tunnel: available"
