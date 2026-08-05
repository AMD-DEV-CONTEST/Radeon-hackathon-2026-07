#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

CHECKPOINT=${CHECKPOINT:-$RADEONNAV_ROOT/experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN/ft1_depth_encoder_epoch6.pt}
OUTPUT_DIR=${OUTPUT_DIR:-$RADEONNAV_ROOT/outputs/recordings/student}
JOBS=${JOBS:-4}
DEVICE=${DEVICE:-cuda}

run_python "$RADEONNAV_ROOT/experiments/neupan_agility/record_amd_videos.py" \
  --checkpoint "$CHECKPOINT" \
  --output-dir "$OUTPUT_DIR" \
  --stack amd-student \
  --no-neupan \
  --jobs "$JOBS" \
  --device "$DEVICE" \
  "$@"

