#!/usr/bin/env bash
# B0 SmolVLA fine-tune on Env-A fruit pick-and-place.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-/workspace/cache/huggingface/lerobot}"
export HF_HOME="${HF_HOME:-/workspace/cache/huggingface}"
export PYTHONUNBUFFERED=1

mkdir -p "$ROOT/output/train" "$ROOT/artifacts/figures" "$ROOT/artifacts/formal"
cd "$ROOT"

N_STEPS="${N_STEPS:-4000}"
BATCH="${BATCH:-4}"
RUN_NAME="${RUN_NAME:-smolvla_fruit_place_b0}"
LOG="$ROOT/output/train_${RUN_NAME}.log"

echo "[run] SmolVLA B0 → $RUN_NAME  steps=$N_STEPS batch=$BATCH"
echo "[run] log: $LOG"

/workspace/rdna/bin/python "$ROOT/scripts/train_smolvla.py" \
  --dataset-id local/franka-kitchen-fruit-place-120ep \
  --pretrained /workspace/models/smolvla_base \
  --vlm-model /workspace/models/SmolVLM2-500M-Video-Instruct \
  --n-steps "$N_STEPS" \
  --batch-size "$BATCH" \
  --num-workers 2 \
  --seed 2026 \
  --log-every 20 \
  --save-every 1000 \
  --output-dir "$ROOT/output" \
  --run-name "$RUN_NAME" \
  2>&1 | tee "$LOG"

echo "[run] done"
