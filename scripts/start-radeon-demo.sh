#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PERSISTENCE_DIR="${LIC_PERSISTENCE_DIR:-/workspace/persistence}"
MODEL="${LIC_RADEON_MODEL:-Qwen/Qwen3-8B-AWQ}"
SERVED_MODEL="${LIC_LLM_MODEL:-qwen3-8b}"
MODEL_PORT="${LIC_MODEL_PORT:-8000}"
APP_PORT="${LIC_APP_PORT:-8765}"
RUNTIME_EVIDENCE="${LIC_RUNTIME_EVIDENCE:-$PERSISTENCE_DIR/local-incident-commander-data/runtime-evidence.json}"

mkdir -p "$PERSISTENCE_DIR/logs"
export HF_HOME="${HF_HOME:-$PERSISTENCE_DIR/huggingface}"

if ! curl -fsS "http://127.0.0.1:${MODEL_PORT}/v1/models" >/dev/null 2>&1; then
  nohup vllm serve "$MODEL" \
    --served-model-name "$SERVED_MODEL" \
    --host 0.0.0.0 \
    --port "$MODEL_PORT" \
    --dtype auto \
    --max-model-len 8192 \
    --max-num-seqs 8 \
    --gpu-memory-utilization 0.85 \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --enforce-eager \
    >"$PERSISTENCE_DIR/logs/vllm.log" 2>&1 &
  echo $! >"$PERSISTENCE_DIR/logs/vllm.pid"
fi

echo "Waiting for vLLM at 127.0.0.1:${MODEL_PORT}..."
for _ in $(seq 1 180); do
  if curl -fsS "http://127.0.0.1:${MODEL_PORT}/v1/models" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:${MODEL_PORT}/v1/models" >/dev/null

cd "$ROOT_DIR"
python3 scripts/write-runtime-evidence.py \
  --models-url "http://127.0.0.1:${MODEL_PORT}/v1/models" \
  --model "$SERVED_MODEL" \
  --output "$RUNTIME_EVIDENCE"

export LIC_ENABLE_LLM=1
export LIC_LLM_BASE_URL="http://127.0.0.1:${MODEL_PORT}/v1"
export LIC_LLM_MODEL="$SERVED_MODEL"
export LIC_RUNTIME_EVIDENCE="$RUNTIME_EVIDENCE"
export LIC_DATA_DIR="${LIC_DATA_DIR:-$PERSISTENCE_DIR/local-incident-commander-data/sessions}"
unset LIC_LLM_API_KEY || true

exec python3 -m incident_commander.server --host 0.0.0.0 --port "$APP_PORT"
