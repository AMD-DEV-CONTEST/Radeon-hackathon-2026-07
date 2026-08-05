#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

TEST_STARTED_SECONDS=$SECONDS
OUTPUT_DIR=${OUTPUT_DIR:-$RADEONNAV_ROOT/outputs/tests/radeon-nav}
CHECKPOINT=${CHECKPOINT:-$RADEONNAV_ROOT/experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN/ft1_depth_encoder_epoch6.pt}
DEVICE=${DEVICE:-cuda}
PLANNER_CONFIG=${PLANNER_CONFIG:-$RADEONNAV_ROOT/experiments/neupan_agility/go2_planner.yaml}
if [[ ${1:-} == --rocm-dune ]]; then
  PLANNER_CONFIG=$RADEONNAV_ROOT/experiments/neupan_agility/go2_planner_rocm_hybrid.yaml
  shift
fi
if (($# > 0)); then
  echo "unknown argument: $1" >&2
  exit 2
fi
mkdir -p "$OUTPUT_DIR"

echo "[1/4] Environment and bundled artifact verification"
run_python "$RADEONNAV_ROOT/setup/verify_environment.py" \
  > "$OUTPUT_DIR/environment.json"

echo "[2/4] NeuPAN example and TSC/BBC interface"
run_python "$RADEONNAV_ROOT/experiments/neupan_agility/run_sanity.py" \
  --device "$DEVICE" \
  --planner-config "$PLANNER_CONFIG" \
  --result "$OUTPUT_DIR/neupan.json"

echo "[3/4] quadrupedal-agility BBC rollout in UniLab MuJoCo"
run_python "$RADEONNAV_ROOT/experiments/neupan_agility/run_bbc_sanity.py" \
  --profile deployment \
  --steps 64 \
  --device "$DEVICE" \
  --output "$OUTPUT_DIR/quadrupedal-agility.json"

echo "[4/4] RadeonNav full-stack smoke"
run_python "$RADEONNAV_ROOT/experiments/neupan_agility/run_radeon_nav.py" \
  --smoke-test \
  --episode-steps 8 \
  --seed 16 \
  --tire-phase t3m1 \
  --device "$DEVICE" \
  --planner-config "$PLANNER_CONFIG" \
  --depth-encoder-checkpoint "$CHECKPOINT" \
  --tag smoke \
  --output-dir "$OUTPUT_DIR/full-stack"

echo "PASSED: NeuPAN, quadrupedal-agility, and RadeonNav elapsed_sec=$((SECONDS - TEST_STARTED_SECONDS))"
