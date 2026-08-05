#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/workspace/QVGM"
MODEL_PATH="${1:-$PROJECT_ROOT/outputs/native_lerobot_smolvla_task7_50ep_20k/checkpoints/020000/pretrained_model}"
OUTPUT_DIR="${2:-$PROJECT_ROOT/outputs/native_lerobot_smolvla_task7_50ep_20k_eval50}"

if [[ ! -f "$MODEL_PATH/config.json" || ! -f "$MODEL_PATH/model.safetensors" ]]; then
  echo "native SmolVLA checkpoint is incomplete: $MODEL_PATH" >&2
  exit 1
fi

export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="/workspace/LIBERO-sim${PYTHONPATH:+:$PYTHONPATH}"
export LIBERO_CONFIG_PATH="$PROJECT_ROOT/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export MUJOCO_EGL_DEVICE_ID=0

cd "$PROJECT_ROOT"
exec .venv-rocm/bin/python scripts/run_smolvla_libero_sweep.py \
  --states 0-49 \
  --seeds 0 \
  --task-id 7 \
  --task-suite libero_spatial \
  --max-steps 240 \
  --action-steps 1 \
  --model-path "$MODEL_PATH" \
  --output-dir "$OUTPUT_DIR"
