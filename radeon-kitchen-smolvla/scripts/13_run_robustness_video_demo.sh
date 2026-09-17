#!/usr/bin/env bash
set -euo pipefail

# Record short, human-readable clips for the final robustness explanation.
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "/workspace/rdna/bin/python" ]]; then
    PYTHON_BIN="/workspace/rdna/bin/python"
  else
    PYTHON_BIN="python"
  fi
fi
CHECKPOINT="${CHECKPOINT:-output/train/smolvla_kitchen_wrist/final}"
DATASET_ID="${DATASET_ID:-local/franka-kitchen-wrist-100ep}"
MANIFEST="${MANIFEST:-analysis/manifests/eval_manifest_seed99_50.json}"
N_EPISODES="${N_EPISODES:-3}"
COMMON=(
  scripts/04_eval_custom_scene.py
  --policy-type smolvla
  --checkpoint "$CHECKPOINT"
  --dataset-id "$DATASET_ID"
  --task "Pick up the cube."
  --camera-layout up_wrist
  --episode-manifest "$MANIFEST"
  --n-episodes "$N_EPISODES"
  --max-steps 150
  --seed 99
  --record-video
)

"$PYTHON_BIN" "${COMMON[@]}" --run-name robustness_video_nominal
"$PYTHON_BIN" "${COMMON[@]}" --occlusion-prob 1.0 --occlusion-fraction 0.40 --run-name robustness_video_occlusion_high
"$PYTHON_BIN" "${COMMON[@]}" --action-delay-steps 4 --run-name robustness_video_delay_high
