#!/bin/bash
# start_incumbent_model.sh — start a disposable incumbent vLLM model on a given port (F3 drill).
# Usage:
#   bash scripts/start_incumbent_model.sh --model-port <port> --served-name <name> [--health-timeout <s>]
set -u

PORT=""
SERVED=""
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"
MODEL_DIR="${LC_INCUMBENT_MODEL_DIR:-/persistent/models/Qwen2.5-14B-Instruct-AWQ}"
while [ $# -gt 0 ]; do
  case "$1" in
    --model-port) PORT="$2"; shift 2;;
    --served-name) SERVED="$2"; shift 2;;
    --health-timeout) HEALTH_TIMEOUT="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$PORT" ] || { echo "start_incumbent: --model-port required" >&2; exit 2; }
[ -n "$SERVED" ] || { echo "start_incumbent: --served-name required" >&2; exit 2; }
[ -d "$MODEL_DIR" ] || { echo "start_incumbent: model dir $MODEL_DIR not found" >&2; exit 1; }

LOG="/tmp/incumbent_vllm_${PORT}.log"
cd /persistent/learning-companion
setsid env \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  HF_ENDPOINT=https://hf-mirror.com \
  VLLM_ATTENTION_BACKEND=ROCM_ATTN \
  /opt/venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_DIR" \
    --served-model-name "$SERVED" \
    --host 0.0.0.0 --port "$PORT" \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.3 \
    --enforce-eager \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
  > "$LOG" 2>&1 < /dev/null &

# readiness poll
for i in $(seq 1 "$HEALTH_TIMEOUT"); do
  curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1 && { echo "START_INCUMBENT_OK: $SERVED on :$PORT"; exit 0; }
  sleep 1
done
echo "START_INCUMBENT_FAIL: timed out waiting for :$PORT (log: $LOG)" >&2
exit 1
