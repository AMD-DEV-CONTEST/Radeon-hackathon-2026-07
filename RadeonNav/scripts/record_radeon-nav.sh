#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

CHECKPOINT=${CHECKPOINT:-$RADEONNAV_ROOT/experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN/ft1_depth_encoder_epoch6.pt}
OUTPUT_DIR=${OUTPUT_DIR:-$RADEONNAV_ROOT/outputs/radeon-nav/seed16-t3m1}
DEVICE=${DEVICE:-cuda}
PLANNER_CONFIG=${PLANNER_CONFIG:-$RADEONNAV_ROOT/experiments/neupan_agility/go2_planner.yaml}
RUNNER_ARGS=()

while (($# > 0)); do
  case "$1" in
    --rocm-dune)
      PLANNER_CONFIG=$RADEONNAV_ROOT/experiments/neupan_agility/go2_planner_rocm_hybrid.yaml
      shift
      ;;
    *)
      RUNNER_ARGS+=("$1")
      shift
      ;;
  esac
done

run_python "$RADEONNAV_ROOT/experiments/neupan_agility/run_radeon_nav.py" \
  --seed 16 \
  --tire-phase t3m1 \
  --episode-steps 7000 \
  --require-upright \
  --device "$DEVICE" \
  --planner-config "$PLANNER_CONFIG" \
  --depth-encoder-checkpoint "$CHECKPOINT" \
  --tag amd-seed16-t3m1 \
  --output-dir "$OUTPUT_DIR" \
  "${RUNNER_ARGS[@]}"
