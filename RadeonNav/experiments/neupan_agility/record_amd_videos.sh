#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
UV_BIN=${UV_BIN:-uv}

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
export MUJOCO_GL=${MUJOCO_GL:-egl}

exec "$UV_BIN" run --project "$ROOT/UniLab" --no-sync python \
  "$ROOT/experiments/neupan_agility/record_amd_videos.py" "$@"
