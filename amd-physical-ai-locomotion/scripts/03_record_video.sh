#!/usr/bin/env bash
# Phase 3 · Render a policy rollout to mp4 for the demo video (headless).
set -euo pipefail
cd "$(dirname "$0")/.."

export MUJOCO_GL="${MUJOCO_GL:-osmesa}"
export XLA_FLAGS="${XLA_FLAGS:---xla_gpu_enable_command_buffer=}"

ENV="${ENV:-Go1JoystickFlatTerrain}"
SEED="${SEED:-0}"
STEPS="${STEPS:-500}"

python3 -m src.render --env "$ENV" --seed "$SEED" --steps "$STEPS"
