#!/usr/bin/env bash
set -euo pipefail

BIGYM_DIR=${BIGYM_DIR:?set BIGYM_DIR to the patched BiGym checkout}
VENV=${VENV:?set VENV to the ROCm Python environment}
REPLAY_PLAN=${REPLAY_PLAN:?set REPLAY_PLAN to a verified 32-episode plan}
SHELL_DIR=${SHELL_DIR:?set SHELL_DIR to the staged shell directory}
DATASET_ROOT=${DATASET_ROOT:?set DATASET_ROOT to the output root}
ROCM_WRAPPER=${ROCM_WRAPPER:-${AMD_BIGYM_ROOT:-/workspace/amd-bigym-3dgs}/toolchains/rocm-wrapper}
TORCH_EXTENSIONS_DIR=${TORCH_EXTENSIONS_DIR:-${AMD_BIGYM_ROOT:-/workspace/amd-bigym-3dgs}/cache/torch-extensions-gsplat}

test -f "$REPLAY_PLAN" || { printf 'Missing replay plan: %s\n' "$REPLAY_PLAN" >&2; exit 2; }
test -f "$SHELL_DIR/profile.json" || { printf 'Missing shell profile. Run stage_visual_shell.sh first.\n' >&2; exit 2; }
test -f "$BIGYM_DIR/d/replay_generation/generate_dataset.py" || {
  printf 'BiGym overlay is not installed: %s\n' "$BIGYM_DIR" >&2
  exit 2
}

export PYTHONUNBUFFERED=1
export PYTHONPATH="$BIGYM_DIR${PYTHONPATH:+:$PYTHONPATH}"
export MUJOCO_GL=${MUJOCO_GL:-egl}
export PYOPENGL_PLATFORM=${PYOPENGL_PLATFORM:-egl}
export ROCM_HOME="$ROCM_WRAPPER"
export PATH="$ROCM_WRAPPER/bin:$PATH"
export PYTORCH_ROCM_ARCH=${PYTORCH_ROCM_ARCH:-gfx1100}
export TORCH_EXTENSIONS_DIR
export MAX_JOBS=${MAX_JOBS:-1}
export HIP_VISIBLE_DEVICES=${HIP_VISIBLE_DEVICES:-0}
export ROCR_VISIBLE_DEVICES=${ROCR_VISIBLE_DEVICES:-$HIP_VISIBLE_DEVICES}

printf 'FORMAL_START task=DishwasherUnloadCutleryLong requested=32 at=%s\n' "$(date -Iseconds)"
"$VENV/bin/python" "$BIGYM_DIR/d/replay_generation/generate_dataset.py" \
  --task DishwasherUnloadCutleryLong \
  --root "$DATASET_ROOT" \
  --replay-plan "$REPLAY_PLAN" \
  --vcodec h264 \
  --camera-set bigym-plus-3 \
  --visual-shell-profile "$SHELL_DIR/profile.json" \
  --visual-shell-strict \
  --image-writer-threads "${IMAGE_WRITER_THREADS:-4}"
printf 'FORMAL_COMPLETE task=DishwasherUnloadCutleryLong requested=32 at=%s\n' "$(date -Iseconds)"
