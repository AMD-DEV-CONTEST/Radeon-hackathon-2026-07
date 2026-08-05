#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

CHECKPOINT=${CHECKPOINT:-$RADEONNAV_ROOT/experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN/ft1_depth_encoder_epoch6.pt}
OUTPUT_DIR=${OUTPUT_DIR:-$RADEONNAV_ROOT/outputs/recordings/neupan-tire}
JOBS=${JOBS:-1}
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

run_python "$RADEONNAV_ROOT/experiments/neupan_agility/record_amd_videos.py" \
  --checkpoint "$CHECKPOINT" \
  --output-dir "$OUTPUT_DIR" \
  --neupan-only \
  --jobs "$JOBS" \
  --device "$DEVICE" \
  --planner-config "$PLANNER_CONFIG" \
  "${RUNNER_ARGS[@]}"
