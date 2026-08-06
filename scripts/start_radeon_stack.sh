#!/usr/bin/env bash
set -euo pipefail

ROOT="${CLAIMCOURT_ROOT:-/workspace/claimcourt}"
MODELS="${CLAIMCOURT_MODELS:-/workspace/models}"
ADAPTER="${CLAIMCOURT_ADAPTER:-/workspace/claimcourt-models/claimcourt-qwen3-14b-intent-lora}"
LOGS="${CLAIMCOURT_LOGS:-/workspace/logs}"
PYTHON="${CLAIMCOURT_PYTHON:-/opt/venv/bin/python}"
VLLM="${CLAIMCOURT_VLLM:-/opt/venv/bin/vllm}"

mkdir -p "$LOGS"

wait_for_url() {
  local url="$1"
  local attempts="${2:-90}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS --max-time 8 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for $url" >&2
  return 1
}

if ! curl -fsS --max-time 3 http://127.0.0.1:8000/v1/models >/dev/null 2>&1; then
  nohup "$VLLM" serve "$MODELS/Qwen3-14B" \
    --host 0.0.0.0 \
    --port 8000 \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.82 \
    --max-model-len 8192 \
    --served-model-name Qwen3-14B \
    --enforce-eager \
    --enable-lora \
    --max-lora-rank 16 \
    --max-loras 1 \
    --lora-modules "claimcourt-intent=$ADAPTER" \
    > "$LOGS/judge-qwen3-14b-lora.log" 2>&1 &
  echo "$!" > "$LOGS/judge-qwen3-14b-lora.pid"
fi
wait_for_url http://127.0.0.1:8000/v1/models

if ! curl -fsS --max-time 3 http://127.0.0.1:8001/v1/models >/dev/null 2>&1; then
  nohup "$VLLM" serve "$MODELS/bge-small-zh-v1.5" \
    --runner pooling \
    --host 0.0.0.0 \
    --port 8001 \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.10 \
    --max-model-len 512 \
    > "$LOGS/embedding-14b-stack.log" 2>&1 &
  echo "$!" > "$LOGS/embedding-14b-stack.pid"
fi
wait_for_url http://127.0.0.1:8001/v1/models

if ! curl -fsS --max-time 3 http://127.0.0.1:8503/api/health >/dev/null 2>&1; then
  api_args=(api.py --host 127.0.0.1 --port 8503)
  if [[ -d "$ROOT/frontend/dist" ]]; then
    api_args+=(--static frontend/dist)
  fi
  (
    cd "$ROOT"
    nohup env \
      CLAIMCOURT_MODEL_ENDPOINT=http://127.0.0.1:8000/v1 \
      CLAIMCOURT_MODEL=Qwen3-14B \
      CLAIMCOURT_ROUTER_ENDPOINT=http://127.0.0.1:8000/v1 \
      CLAIMCOURT_ROUTER_MODEL=claimcourt-intent \
      CLAIMCOURT_GPU_NAME="AMD Radeon PRO W7900" \
      "$PYTHON" "${api_args[@]}" \
      > "$LOGS/api-qwen3-14b.log" 2>&1 &
    echo "$!" > "$LOGS/api-qwen3-14b.pid"
  )
fi
wait_for_url http://127.0.0.1:8503/api/health 30

curl -fsS http://127.0.0.1:8000/v1/models
printf '\n'
curl -fsS http://127.0.0.1:8001/v1/models
printf '\n'
curl -fsS http://127.0.0.1:8503/api/health
printf '\n'
