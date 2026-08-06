#!/usr/bin/env bash
# Continue π0.5 fine-tune from B1 final (grasp recovery attempt).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-/workspace/cache/huggingface/lerobot}"
export HF_HOME="${HF_HOME:-/workspace/cache/huggingface}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1

/workspace/rdna/bin/python scripts/train_pi05.py \
  --pretrained "$ROOT/output/train/pi05_fruit_place_b1/final" \
  --n-steps 4000 \
  --batch-size 2 \
  --num-workers 2 \
  --seed 2026 \
  --lr 1.5e-5 \
  --run-name pi05_fruit_place_b1c \
  --save-every 1000 \
  --log-every 20 \
  2>&1 | tee "$ROOT/output/train_pi05_fruit_place_b1c.log"

echo "[train] B1c done"
