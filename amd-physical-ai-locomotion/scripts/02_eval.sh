#!/usr/bin/env bash
# Phase 2 · Closed-loop evaluation of the trained policy on the AMD GPU.
set -euo pipefail
cd "$(dirname "$0")/.."

export MUJOCO_GL="${MUJOCO_GL:-osmesa}"
export XLA_FLAGS="${XLA_FLAGS:---xla_gpu_enable_command_buffer=}"

ENV="${ENV:-Go1JoystickFlatTerrain}"
SEED="${SEED:-0}"
EPISODES="${EPISODES:-5}"

python3 -m src.eval --env "$ENV" --seed "$SEED" --episodes "$EPISODES"
