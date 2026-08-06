#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
REPO="${REPO:-$ROOT/repo}"
MODEL_ID="${MODEL_ID:-Qwen/Qwen2.5-0.5B-Instruct}"
PORT="${VLLM_PORT:-8000}"
LOG_FILE="${LOG_FILE:-$ROOT/logs/vllm-smoke.log}"
PID_FILE="${PID_FILE:-$ROOT/logs/vllm-smoke.pid}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-180}"

mkdir -p "$ROOT/logs"
rm -f "$LOG_FILE" "$PID_FILE"

cleanup() {
  if [[ -f "$PID_FILE" ]]; then
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
    fi
  fi
}
trap cleanup EXIT

cd "$REPO"
nohup env \
  MODEL_PATH="$MODEL_ID" \
  SERVED_MODEL_NAME="$MODEL_ID" \
  MODEL_SNAPSHOT_VERIFY=0 \
  VLLM_PORT="$PORT" \
  VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-2048}" \
  VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.20}" \
  VLLM_MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-2}" \
  bash scripts/serve_vllm.sh >"$LOG_FILE" 2>&1 </dev/null &
echo "$!" > "$PID_FILE"

deadline=$((SECONDS + TIMEOUT_SECONDS))
until curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; do
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ERROR: vLLM exited before becoming healthy."
    tail -n 160 "$LOG_FILE"
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "ERROR: vLLM did not become healthy within ${TIMEOUT_SECONDS}s."
    tail -n 160 "$LOG_FILE"
    exit 1
  fi
  sleep 2
done

curl -fsS "http://127.0.0.1:$PORT/v1/models" >/dev/null

chat_response="$(
  curl -fsS "http://127.0.0.1:$PORT/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly CHAT_OK\"}],\"temperature\":0,\"max_tokens\":32}"
)"

responses_response="$(
  curl -fsS "http://127.0.0.1:$PORT/v1/responses" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL_ID\",\"input\":\"Reply with exactly RESPONSE_OK\",\"max_output_tokens\":32}"
)"

"$ROOT/venvs/agent/bin/python" - "$chat_response" "$responses_response" <<'PY'
import json
import sys

chat = json.loads(sys.argv[1])
responses = json.loads(sys.argv[2])
assert chat["object"] == "chat.completion", chat
assert responses["object"] == "response", responses
assert responses["status"] == "completed", responses
print("VLLM_CHAT_COMPLETIONS_OK")
print("VLLM_RESPONSES_OK")
PY

"$ROOT/venvs/agent/bin/python" scripts/benchmark_openai_api.py \
  --model "$MODEL_ID" \
  --iterations "${BENCHMARK_ITERATIONS:-3}" \
  --max-tokens "${BENCHMARK_MAX_TOKENS:-64}" \
  --output "$ROOT/logs/vllm-smoke-benchmark.json"

echo "VLLM_SMOKE_OK"
