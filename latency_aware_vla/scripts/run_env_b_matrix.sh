#!/usr/bin/env bash
# Env-B formal matrix: held-out runtime fruit XY shift (3–5 cm).
#
# Design (paired, fair):
#   - Same fruit-init seed=99 as Env-A → identical nominal poses
#   - Independent perturb RNG (seed+7919): |Δxy| ~ U[3,5] cm, random angle
#   - Basket fixed; shift never in training
#   - Sync-full E=50, max_steps=400, native delay (capability, not latency)
#   - Policies: SmolVLA B0 + π0.5 B1d (best closed-loop checkpoints)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PY:-/workspace/rdna/bin/python}"
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-/workspace/cache/huggingface/lerobot}"
export HF_HOME="${HF_HOME:-/workspace/cache/huggingface}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1

SMOL="$ROOT/output/train/smolvla_fruit_place_b0/final"
PI05="$ROOT/output/train/pi05_fruit_place_b1d/final"
SEED=99
E=50
MAX_STEPS=400
N=20

run() {
  local policy="$1" ckpt="$2" name="$3"
  echo "========================================"
  echo "[env-b] $name"
  echo "========================================"
  "$PY" scripts/eval_pick_place.py \
    --policy "$policy" \
    --checkpoint "$ckpt" \
    --env-b \
    --perturb-m-min 0.03 \
    --perturb-m-max 0.05 \
    --n-episodes "$N" \
    --action-horizon "$E" \
    --max-steps "$MAX_STEPS" \
    --seed "$SEED" \
    --run-name "$name" \
    --record-video
}

run smolvla "$SMOL" smolvla_sync_E50_envb_n20
run pi05 "$PI05" pi05_sync_E50_b1d_envb_n20

"$PY" scripts/plot_env_a_vs_b.py

"$PY" scripts/make_demo_reel.py \
  --summaries \
    output/eval/smolvla_sync_E50_envb_n20/eval_summary.json \
    output/eval/pi05_sync_E50_b1d_envb_n20/eval_summary.json \
  --out output/demo/env_b_reel.mp4 \
  --max-clips 6

# Copy formal
mkdir -p artifacts/formal/smolvla_sync_E50_envb_n20 artifacts/formal/pi05_sync_E50_b1d_envb_n20
cp -f output/eval/smolvla_sync_E50_envb_n20/eval_summary.json artifacts/formal/smolvla_sync_E50_envb_n20/
cp -f output/eval/pi05_sync_E50_b1d_envb_n20/eval_summary.json artifacts/formal/pi05_sync_E50_b1d_envb_n20/
cp -f artifacts/env_b_manifest.json artifacts/formal/env_b_manifest.json 2>/dev/null || true

echo "[env-b] DONE"
