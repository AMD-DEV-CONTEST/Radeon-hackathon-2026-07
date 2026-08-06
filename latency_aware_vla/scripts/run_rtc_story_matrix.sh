#!/usr/bin/env bash
# Story-closing RTC matrix on SmolVLA (paired seed=99 vs existing Sync runs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PY:-/workspace/rdna/bin/python}"
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-/workspace/cache/huggingface/lerobot}"
export HF_HOME="${HF_HOME:-/workspace/cache/huggingface}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1

CKPT="$ROOT/output/train/smolvla_fruit_place_b0/final"
SEED=99
E=10
MAX_STEPS=400

run() {
  local mode="$1" name="$2" n="$3" delay="$4"
  echo "========================================"
  echo "[rtc-matrix] $name mode=$mode n=$n delay=${delay}ms E=$E"
  echo "========================================"
  "$PY" scripts/eval_rtc_pick_place.py \
    --policy smolvla \
    --checkpoint "$CKPT" \
    --mode "$mode" \
    --n-episodes "$n" \
    --execution-horizon "$E" \
    --max-steps "$MAX_STEPS" \
    --seed "$SEED" \
    --delay-ms "$delay" \
    --native-infer-ms 343 \
    --run-name "$name" \
    --record-video
}

# Smoke
run rtc smolvla_rtc_E10_smoke3 3 0

# Formal story arms
run rtc smolvla_rtc_E10_n20 20 0
run rtc smolvla_rtc_E10_d200_n20 20 200
run async smolvla_async_E10_d200_n20 20 200

# Plots vs existing Sync
"$PY" scripts/plot_eval_results.py \
  --summaries \
    output/eval/smolvla_sync_E50_n20_s400/eval_summary.json \
    output/eval/smolvla_sync_E50_d200_n20_s400/eval_summary.json \
    output/eval/smolvla_rtc_E10_n20/eval_summary.json \
    output/eval/smolvla_rtc_E10_d200_n20/eval_summary.json \
    output/eval/smolvla_async_E10_d200_n20/eval_summary.json \
  --out-dir artifacts/figures/eval \
  --tag env_a_rtc_story

"$PY" scripts/make_demo_reel.py \
  --summaries \
    output/eval/smolvla_rtc_E10_d200_n20/eval_summary.json \
    output/eval/smolvla_sync_E50_d200_n20_s400/eval_summary.json \
  --out output/demo/rtc_vs_sync_d200_reel.mp4 \
  --max-clips 8

echo "[rtc-matrix] DONE"
