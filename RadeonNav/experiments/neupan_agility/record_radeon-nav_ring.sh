#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UV_BIN="${UV_BIN:-/opt/venv/bin/uv}"
CHECKPOINT="${CHECKPOINT:-$ROOT/experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN/ft1_depth_encoder_epoch6.pt}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/outputs/radeon-nav/through-ring}"
TIRE_PHASE="${TIRE_PHASE:-t3}"
TAG="${TAG:-amd-t3-through-ring-diagnostic}"

# `cuda` is PyTorch's API spelling for the HIP device. The result JSON records
# the actual AMD device name and torch.version.hip so this cannot be mistaken
# for an NVIDIA run.
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" \
MUJOCO_GL="${MUJOCO_GL:-egl}" \
  "$UV_BIN" run --no-sync --project "$ROOT/UniLab" python \
  "$ROOT/experiments/neupan_agility/run_radeon_nav.py" \
  --seed 7 \
  --device cuda \
  --tire-phase "$TIRE_PHASE" \
  --depth-encoder-checkpoint "$CHECKPOINT" \
  --tag "$TAG" \
  --output-dir "$OUTPUT_DIR"
