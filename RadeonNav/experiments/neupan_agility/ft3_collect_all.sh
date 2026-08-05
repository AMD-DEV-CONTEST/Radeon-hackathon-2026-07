#!/usr/bin/env bash
# M-FT-3 DAgger round-3 collection: preregistered mix, seeds 900-1019,
# ep6 student acting, teacher labels, per-step forbidden flags.
set -u
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"
UV_BIN=${UV_BIN:-uv}
EP6=experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN/ft1_depth_encoder_epoch6.pt
OUT=experiment-results/quadrupedal-agility/FT3-DATA
LOG=$OUT/collect.log
mkdir -p "$OUT"

collect () {
  local family=$1 scene=$2 seed=$3
  if [ -f "$OUT/${family}_${scene}_seed${seed}.npz" ]; then
    echo "skip ${family}_${scene}_seed${seed}" >> "$LOG"
    return 0
  fi
  CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0} "$UV_BIN" run --project UniLab --no-sync python \
    experiments/neupan_agility/ft_collect.py \
    --family "$family" --scene "$scene" --seed "$seed" \
    --output-dir "$OUT" --depth-encoder-checkpoint "$EP6" \
    >> "$LOG" 2>&1 || echo "FAILED ${family}_${scene}_seed${seed}" >> "$LOG"
}

for seed in $(seq 900 929);   do collect source tire_jump "$seed"; done
for seed in $(seq 930 959);   do collect source seesaw    "$seed"; done
for seed in $(seq 960 969);   do collect source frame     "$seed"; done
for seed in $(seq 970 979);   do collect source tunnel    "$seed"; done
for seed in $(seq 980 989);   do collect source poles     "$seed"; done
for seed in $(seq 990 999);   do collect planner TF       "$seed"; done
for seed in $(seq 1000 1009); do collect planner TR       "$seed"; done
for seed in $(seq 1010 1019); do collect planner TS       "$seed"; done
echo "COLLECTION_DONE $(ls "$OUT"/*.npz 2>/dev/null | wc -l) episodes" >> "$LOG"
