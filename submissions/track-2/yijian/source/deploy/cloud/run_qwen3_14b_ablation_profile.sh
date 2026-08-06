#!/usr/bin/env bash
set -euo pipefail

PREFIX_CACHE="${1:?first argument must be 0 or 1 for prefix caching}"
MAX_MODEL_LEN="${2:?second argument must be 8192 or 16384}"
OUTPUT="${3:?third argument must be the output JSON path}"
[[ "$PREFIX_CACHE" == "0" || "$PREFIX_CACHE" == "1" ]] || { echo "invalid prefix cache value" >&2; exit 2; }
[[ "$MAX_MODEL_LEN" == "8192" || "$MAX_MODEL_LEN" == "16384" ]] || { echo "invalid maximum model length" >&2; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
PYTHON_BIN="${YIJIAN_CLOUD_PYTHON:-/workspace/yijian-venv/bin/python}"
KATAGO="${YIJIAN_KATAGO_BIN:-$PERSIST_ROOT/katago-v1.16.5/build/katago}"
KATAGO_MODEL="${YIJIAN_KATAGO_MODEL:-$PERSIST_ROOT/katago-models/kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz}"
KATAGO_CONFIG="${YIJIAN_KATAGO_CONFIG:-$PERSIST_ROOT/katago-v1.16.5/analysis.cfg}"
RESTORE_27B="${YIJIAN_RESTORE_27B:-/workspace/yijian/lora-gold-v2/bin/restore_27b.sh}"

restore_services() {
  "$SCRIPT_DIR/stop_qwen3_14b_agent.sh" >/dev/null 2>&1 || true
  "$RESTORE_27B" >/dev/null 2>&1 || true
}
trap restore_services EXIT

mapfile -t service_pids < <(pgrep -x llama-server || true)
if ((${#service_pids[@]})); then
  kill "${service_pids[@]}"
  for _ in $(seq 1 30); do
    pgrep -x llama-server >/dev/null || break
    sleep 1
  done
fi
pgrep -x llama-server >/dev/null && { echo "27B service did not stop" >&2; exit 3; }

YIJIAN_VLLM_GPU_MEMORY_UTILIZATION=0.72 \
YIJIAN_VLLM_ENABLE_PREFIX_CACHING="$PREFIX_CACHE" \
YIJIAN_VLLM_MAX_MODEL_LEN="$MAX_MODEL_LEN" \
  "$SCRIPT_DIR/start_qwen3_14b_agent.sh"

mkdir -p "$(dirname -- "$OUTPUT")"
YIJIAN_VLLM_GPU_MEMORY_UTILIZATION=0.72 \
  "$PYTHON_BIN" "$SCRIPT_DIR/stress_qwen3_katago_coexist.py" \
    --katago "$KATAGO" \
    --katago-model "$KATAGO_MODEL" \
    --katago-config "$KATAGO_CONFIG" \
    --cycles 30 --p95-limit 12 \
    --vllm-log "$PERSIST_ROOT/logs/qwen3-14b-agent-8083.log" \
    --output "$OUTPUT"

echo "ablation profile complete: prefix=$PREFIX_CACHE max-model-len=$MAX_MODEL_LEN"
