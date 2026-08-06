#!/usr/bin/env bash
set -euo pipefail

# Reproduce the optimized Radeon configuration used for the recorded 80B run.
# This launcher only manages the PID that it creates; it never stops another
# llama-server process.

MODEL="${MODEL:?set MODEL to Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf}"
LLAMA_SERVER="${LLAMA_SERVER:?set LLAMA_SERVER to the ROCm/HIP llama-server binary}"
API_KEY_FILE="${API_KEY_FILE:?set API_KEY_FILE to a non-empty bearer-token file}"
STATE_DIR="${STATE_DIR:?set STATE_DIR to a writable directory for the PID and log}"

MODEL_ALIAS="${MODEL_ALIAS:-Qwen3-Next-80B-A3B-Instruct}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
CONTEXT_TOKENS="${CONTEXT_TOKENS:-262144}"
GPU_LAYERS="${GPU_LAYERS:-47}"
KV_CACHE_TYPE="${KV_CACHE_TYPE:-q4_0}"
THREADS="${THREADS:-32}"
PARALLEL_SLOTS="${PARALLEL_SLOTS:-1}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-180}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${PORT}/health}"

EXPECTED_MODEL_BYTES=48410988384

test -s "$MODEL"
test -x "$LLAMA_SERVER"
test -s "$API_KEY_FILE"

actual_model_bytes="$(stat -c '%s' "$MODEL")"
if [[ "$actual_model_bytes" != "$EXPECTED_MODEL_BYTES" ]]; then
  printf 'unexpected model size: got %s, expected %s bytes\n' \
    "$actual_model_bytes" "$EXPECTED_MODEL_BYTES" >&2
  exit 1
fi

api_key_mode="$(stat -c '%a' "$API_KEY_FILE")"
if (( (8#$api_key_mode & 077) != 0 )); then
  printf 'API key file must not be group/world accessible: mode=%s\n' "$api_key_mode" >&2
  exit 1
fi

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
LOG_FILE="$STATE_DIR/qwen3-next-80b.log"
PID_FILE="$STATE_DIR/qwen3-next-80b.pid"

if [[ -s "$PID_FILE" ]]; then
  previous_pid="$(<"$PID_FILE")"
  if [[ "$previous_pid" =~ ^[0-9]+$ ]] && kill -0 "$previous_pid" 2>/dev/null; then
    printf 'refusing to start: recorded PID %s is still alive\n' "$previous_pid" >&2
    exit 1
  fi
fi

if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
  printf 'refusing to start: an existing service already answers at %s\n' "$HEALTH_URL" >&2
  exit 1
fi

server_dir="$(dirname "$LLAMA_SERVER")"
server_command=(
  "$LLAMA_SERVER"
  -m "$MODEL"
  --alias "$MODEL_ALIAS"
  --host "$HOST"
  --port "$PORT"
  --jinja
  -fa on
  -c "$CONTEXT_TOKENS"
  -ngl "$GPU_LAYERS"
  -t "$THREADS"
  -tb "$THREADS"
  -np "$PARALLEL_SLOTS"
  --cache-type-k "$KV_CACHE_TYPE"
  --cache-type-v "$KV_CACHE_TYPE"
  --temp 0.7
  --top-p 0.8
  --top-k 20
  --api-key-file "$API_KEY_FILE"
)

umask 077
nohup env LD_LIBRARY_PATH="$server_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "${server_command[@]}" >"$LOG_FILE" 2>&1 &
server_pid=$!
printf '%s\n' "$server_pid" >"$PID_FILE"

cleanup_failed_start() {
  local status=$?
  if kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  trap - EXIT
  exit "$status"
}
trap cleanup_failed_start EXIT

deadline=$((SECONDS + STARTUP_TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    printf 'llama-server exited during startup\n' >&2
    tail -n 100 "$LOG_FILE" >&2 || true
    exit 1
  fi
  if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
    trap - EXIT
    printf 'llama-server ready pid=%s url=%s\n' "$server_pid" "$HEALTH_URL"
    exit 0
  fi
  sleep 2
done

printf 'llama-server readiness timeout after %s seconds\n' "$STARTUP_TIMEOUT_SECONDS" >&2
tail -n 100 "$LOG_FILE" >&2 || true
exit 1
