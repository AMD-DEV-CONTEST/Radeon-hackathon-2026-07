#!/usr/bin/env bash
# Formal Sync eval matrix (conference protocol).
# Finding: E=10 on gradual-approach chunks stalls near home (prefix attractor).
# Primary success metrics use Sync-full E=50 (=chunk_size); E=10 kept as ablation.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PY:-/workspace/rdna/bin/python}"
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-/workspace/cache/huggingface/lerobot}"
export HF_HOME="${HF_HOME:-/workspace/cache/huggingface}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export PYTHONUNBUFFERED=1

SMOL_CKPT="$ROOT/output/train/smolvla_fruit_place_b0/final"
PI05_CKPT="$ROOT/output/train/pi05_fruit_place_b1/final"
SEED=99
MAX_STEPS=250  # match expert episode length

run_eval() {
  local policy="$1" ckpt="$2" name="$3" n="$4" E="$5" delay="${6:-0}"
  echo "========================================"
  echo "[matrix] $name  policy=$policy n=$n E=$E delay=${delay}ms"
  echo "========================================"
  "$PY" scripts/eval_pick_place.py \
    --policy "$policy" \
    --checkpoint "$ckpt" \
    --n-episodes "$n" \
    --action-horizon "$E" \
    --max-steps "$MAX_STEPS" \
    --seed "$SEED" \
    --delay-ms "$delay" \
    --run-name "$name" \
    --record-video
}

# 1) Primary: Sync-full E=50, 20ep, paired seed, native latency
run_eval pi05 "$PI05_CKPT" pi05_sync_E50_n20 20 50 0
run_eval smolvla "$SMOL_CKPT" smolvla_sync_E50_n20 20 50 0

# 2) Ablation: Sync-short E=10 (RTC-matched horizon)
run_eval pi05 "$PI05_CKPT" pi05_sync_E10_n20 20 10 0
run_eval smolvla "$SMOL_CKPT" smolvla_sync_E10_n20 20 10 0

# 3) Latency injection +200ms on Sync-full (motivation for RTC)
run_eval pi05 "$PI05_CKPT" pi05_sync_E50_d200_n20 20 50 200
run_eval smolvla "$SMOL_CKPT" smolvla_sync_E50_d200_n20 20 50 200

# 4) Conference plots
"$PY" scripts/plot_eval_results.py \
  --summaries \
    output/eval/smolvla_sync_E50_n20/eval_summary.json \
    output/eval/pi05_sync_E50_n20/eval_summary.json \
    output/eval/smolvla_sync_E10_n20/eval_summary.json \
    output/eval/pi05_sync_E10_n20/eval_summary.json \
  --out-dir artifacts/figures/eval \
  --tag env_a_sync_E_ablation

"$PY" scripts/plot_eval_results.py \
  --summaries \
    output/eval/smolvla_sync_E50_n20/eval_summary.json \
    output/eval/pi05_sync_E50_n20/eval_summary.json \
    output/eval/smolvla_sync_E50_d200_n20/eval_summary.json \
    output/eval/pi05_sync_E50_d200_n20/eval_summary.json \
  --out-dir artifacts/figures/eval \
  --tag env_a_sync_latency

# Write finding note
mkdir -p artifacts/formal/eval_notes
cat > artifacts/formal/eval_notes/chunk_prefix_attractor.md <<'EOF'
# Sync execution-horizon finding

Open-loop probe (HOME state + eval camera): π0.5 chunk `||a_t - home||` at
t={0,10,25,49} ≈ {0.07, 0.19, 0.60, 0.92}. Expert demos show the same gradual
warmup. With E=10 Sync (take prefix then replan), the robot remains near the
start-of-chunk attractor and fruit lift stays ≈0. Sync-full E=50 (=chunk_size)
executes the planned reach and is the primary success metric; E=10 is retained
as an ablation that motivates RTC / longer effective horizons under latency.
EOF

echo "[matrix] ALL DONE"
