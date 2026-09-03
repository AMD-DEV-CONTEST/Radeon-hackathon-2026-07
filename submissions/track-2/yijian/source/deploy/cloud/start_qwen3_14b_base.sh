#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="${YIJIAN_WORKSPACE_ROOT:-/workspace/yijian}"
PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
VLLM="${YIJIAN_VLLM_BIN:-$WORKSPACE_ROOT/vllm-venv/bin/vllm}"
MODEL="${YIJIAN_QWEN3_14B_MODEL_PATH:-$WORKSPACE_ROOT/qwen3-14b-bf16}"
PORT="${YIJIAN_QWEN3_14B_PORT:-8083}"
GPU_UTIL="${YIJIAN_VLLM_GPU_MEMORY_UTILIZATION:-0.72}"
MAX_MODEL_LEN="${YIJIAN_VLLM_MAX_MODEL_LEN:-8192}"
MAX_NUM_SEQS="${YIJIAN_VLLM_MAX_NUM_SEQS:-2}"
ALIAS="${YIJIAN_QWEN3_14B_BASE_ALIAS:-Qwen3-14B-Public-Repro}"
LOG="$PERSIST_ROOT/logs/qwen3-14b-base-$PORT.log"
PID_FILE="$PERSIST_ROOT/qwen3-14b-base-$PORT.pid"

[[ -x "$VLLM" ]] || { echo "vLLM executable not found: $VLLM" >&2; exit 1; }
[[ -f "$MODEL/config.json" ]] || { echo "Qwen3-14B model not found: $MODEL" >&2; exit 1; }
mkdir -p "$PERSIST_ROOT/logs"

nohup "$VLLM" serve "$MODEL" \
  --served-model-name "$ALIAS" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --dtype bfloat16 \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --enable-prefix-caching \
  >"$LOG" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 240); do
  if curl -fsS "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -Fq "$ALIAS"; then
    echo "Qwen3-14B public reproduction service is ready: $ALIAS"
    exit 0
  fi
  sleep 1
done

tail -120 "$LOG" >&2 || true
echo "Qwen3-14B service did not become ready within 240 seconds." >&2
exit 1
