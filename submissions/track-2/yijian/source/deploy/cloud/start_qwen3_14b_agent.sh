#!/usr/bin/env bash
set -euo pipefail

PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
WORKSPACE_ROOT="${YIJIAN_WORKSPACE_ROOT:-/workspace/yijian}"
VLLM="$WORKSPACE_ROOT/vllm-venv/bin/vllm"
MODEL="${YIJIAN_QWEN3_14B_MODEL_PATH:-$WORKSPACE_ROOT/qwen3-14b-bf16}"
ADAPTER="${YIJIAN_QWEN3_14B_ADAPTER_PATH:-$PERSIST_ROOT/models/yijian-lora-v3-frozen/adapter}"
ALIAS="${YIJIAN_QWEN3_14B_ALIAS:-yijian-lora}"
DISPLAY_NAME="${YIJIAN_QWEN3_14B_DISPLAY_NAME:-弈鉴 LoRA}"
PORT="${YIJIAN_QWEN3_14B_PORT:-8083}"
GPU_UTIL="${YIJIAN_VLLM_GPU_MEMORY_UTILIZATION:-0.72}"
MAX_MODEL_LEN="${YIJIAN_VLLM_MAX_MODEL_LEN:-8192}"
MAX_NUM_SEQS="${YIJIAN_VLLM_MAX_NUM_SEQS:-2}"
PREFIX_CACHE="${YIJIAN_VLLM_ENABLE_PREFIX_CACHING:-1}"
LOG="$PERSIST_ROOT/logs/qwen3-14b-agent-$PORT.log"
PID_FILE="$PERSIST_ROOT/qwen3-14b-agent-$PORT.pid"

[[ -x "$VLLM" ]] || { echo "vLLM环境尚未安装：$VLLM" >&2; exit 1; }
[[ -f "$MODEL/config.json" ]] || { echo "Qwen3-14B基座不存在：$MODEL" >&2; exit 1; }
[[ -f "$ADAPTER/adapter_config.json" ]] || { echo "LoRA adapter不存在：$ADAPTER" >&2; exit 1; }
mkdir -p "$PERSIST_ROOT/logs"

if curl -fsS "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -Fq "$ALIAS"; then
  echo "$DISPLAY_NAME 已在$PORT端口运行。"
  exit 0
fi
if curl -fsS "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
  echo "$PORT端口正被另一模型占用。" >&2
  exit 2
fi

prefix_args=()
if [[ "$PREFIX_CACHE" == "1" ]]; then
  prefix_args+=(--enable-prefix-caching)
fi

nohup "$VLLM" serve "$MODEL" \
  --served-model-name Qwen3-14B \
  --host 127.0.0.1 \
  --port "$PORT" \
  --dtype bfloat16 \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --gpu-memory-utilization "$GPU_UTIL" \
  "${prefix_args[@]}" \
  --enable-lora \
  --max-lora-rank 16 \
  --lora-modules "$ALIAS=$ADAPTER" \
  >"$LOG" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 240); do
  if curl -fsS "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -Fq "$ALIAS"; then
    echo "$DISPLAY_NAME 已就绪：$ALIAS"
    exit 0
  fi
  sleep 1
done

tail -120 "$LOG" >&2 || true
echo "$DISPLAY_NAME 未能在240秒内就绪。" >&2
exit 1
