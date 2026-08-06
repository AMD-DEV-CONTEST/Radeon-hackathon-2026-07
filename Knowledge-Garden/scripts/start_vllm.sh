#!/bin/bash
# start_vllm.sh — start one vLLM server for a given model on a given port.
# Usage:
#   bash scripts/start_vllm.sh <model_dir> <model_name> <port> [gpu_util] [max_model_len]
# Example:
#   bash scripts/start_vllm.sh /persistent/models/Qwen2.5-14B-Instruct Qwen2.5-14B-Instruct 8000 0.45 8192
set -u
MODEL_DIR="${1:?model_dir required}"
MODEL_NAME="${2:?model_name required}"
PORT="${3:?port required}"
GPU_UTIL="${4:-0.45}"
MAX_LEN="${5:-8192}"

LOG="/persistent/models/vllm_${PORT}.log"
cd "$(dirname "$0")/.."

echo "[start_vllm] $MODEL_NAME on :$PORT (gpu_util=$GPU_UTIL, max_len=$MAX_LEN)"
setsid env \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  HF_ENDPOINT=https://hf-mirror.com \
  VLLM_ATTENTION_BACKEND=ROCM_ATTN \
  /opt/venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_DIR" \
    --served-model-name "$MODEL_NAME" \
    --host 0.0.0.0 --port "$PORT" \
    --max-model-len "$MAX_LEN" \
    --gpu-memory-utilization "$GPU_UTIL" \
    --enforce-eager \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
  > "$LOG" 2>&1 < /dev/null &
echo "PID $! | log: $LOG | 等待就绪..."
