#!/usr/bin/env bash
set -euo pipefail

ROOT=/workspace/yijian/lora-data-closure-v1
MODEL=/workspace/yijian/qwen3-14b-bf16
RUN="$ROOT/runs/smoke-4step-v1"
REVISION=40c069824f4251a91eefaf281ebe4c544efd3e18

test -f "$ROOT/audits/qwen3-14b-download-complete.txt"
test ! -e "$RUN"
mkdir -p "$ROOT/runs" "$ROOT/logs"

restore_27b() {
  "$ROOT/bin/restore_27b.sh" >> "$ROOT/logs/restore-27b-after-smoke.log" 2>&1 || true
}
trap restore_27b EXIT

mapfile -t service_pids < <(pgrep -f "llama-server.*--port 8082" || true)
if ((${#service_pids[@]})); then
  kill "${service_pids[@]}"
  for _ in $(seq 1 30); do
    pgrep -f "llama-server.*--port 8082" >/dev/null || break
    sleep 1
  done
fi
if pgrep -f "llama-server.*--port 8082" >/dev/null; then
  mapfile -t service_pids < <(pgrep -f "llama-server.*--port 8082")
  kill -9 "${service_pids[@]}"
fi

sleep 3
PYTORCH_HIP_ALLOC_CONF=expandable_segments:True \
TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
/workspace/yijian-venv/bin/python "$ROOT/bin/train_lora_rocm.py" \
  --model "$MODEL" \
  --model-revision "$REVISION" \
  --manifest "$ROOT/data/manifest.json" \
  --train "$ROOT/data/agent_sft_train.jsonl" \
  --eval "$ROOT/data/agent_sft_dev.jsonl" \
  --output "$RUN" \
  --epochs 1 \
  --max-steps 4 \
  --gradient-accumulation 1 \
  --train-limit 8 \
  --max-length 1536 \
  --max-peak-reserved-gib 45
