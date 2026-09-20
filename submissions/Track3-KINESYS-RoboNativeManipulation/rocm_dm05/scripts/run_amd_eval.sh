#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 native|3dgs MODEL_PATH DEMO_PATH OUTPUT_DIR" >&2
  exit 2
fi

MODE=$1
MODEL_PATH=$2
DEMO_PATH=$3
OUTPUT_DIR=$4
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

: "${PYTHON:?Set PYTHON to the ROCm environment Python executable}"
: "${OPENDM_ROOT:?Set OPENDM_ROOT to the patched OpenDM checkout}"

if [[ "$MODE" != native && "$MODE" != 3dgs ]]; then
  echo "Mode must be native or 3dgs" >&2
  exit 2
fi

args=(
  --mode "$MODE"
  --opendm-root "$OPENDM_ROOT"
  --model-path "$MODEL_PATH"
  --demo "$DEMO_PATH"
  --output-dir "$OUTPUT_DIR"
  --gpus "${AMD_GPU_IDS:-0}"
  --seed-start "${SEED_START:-200000}"
  --num-episodes "${NUM_EPISODES:-50}"
  --diffusion-steps "${DIFFUSION_STEPS:-10}"
)

if [[ "$MODE" == 3dgs ]]; then
  : "${BIGYM_3DGS_ROOT:?Set BIGYM_3DGS_ROOT for 3dgs evaluation}"
  : "${VISUAL_SHELL_PROFILE:?Set VISUAL_SHELL_PROFILE for 3dgs evaluation}"
  args+=(
    --three-dgs-root "$BIGYM_3DGS_ROOT"
    --visual-shell-profile "$VISUAL_SHELL_PROFILE"
  )
fi

exec "$PYTHON" "$PROJECT_ROOT/scripts/run_eval.py" "${args[@]}"
