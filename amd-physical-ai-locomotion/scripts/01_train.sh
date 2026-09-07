#!/usr/bin/env bash
# Phase 1 · Train the locomotion policy on the AMD GPU.
#   ENV=Go1JoystickFlatTerrain (quadruped, default) or G1JoystickFlatTerrain (humanoid)
#   SMOKE=1 runs a tiny 200k-step run just to confirm the pipeline works.
#
# Uses our from-scratch single-GPU jit PPO (src/train_jax_ppo.py), NOT brax's
# PPO runner — the latter segfaults in libhsa-runtime64 on this gfx1100/ROCm
# stack (see docs/ROCM_BUG_REPORT.md (Root Cause Analysis)). Set TRAINER=brax to use the old path.
set -euo pipefail
cd "$(dirname "$0")/.."

export MUJOCO_GL="${MUJOCO_GL:-osmesa}"
export XLA_FLAGS="${XLA_FLAGS:---xla_gpu_enable_command_buffer=}"

ENV="${ENV:-Go1JoystickFlatTerrain}"
SEED="${SEED:-0}"
TRAINER="${TRAINER:-jax}"   # jax = our single-GPU PPO; brax = original brax runner

# NOTE (2026-07-17): the rocprofiler HSA segfault is a NON-DETERMINISTIC race,
# not a size threshold — no NUM_ENVS/ITERS_PER_CHUNK is "proven stable". 512/4
# and even 256/1 crashed before the first checkpoint (see docs/ROCM_BUG_REPORT.md).
# These defaults are only a starting point; the real fix is a profiler-free
# xla_rocm plugin (§9.7 path A), NOT tuning these numbers.
NUM_ENVS="${NUM_ENVS:-512}"
ITERS_PER_CHUNK="${ITERS_PER_CHUNK:-4}"
NUM_TIMESTEPS="${NUM_TIMESTEPS:-50000000}"
MAX_RESTARTS="${MAX_RESTARTS:-200}"   # auto-resume budget across HSA segfaults

if [ "$TRAINER" = "brax" ]; then
  MODULE="src.train"
else
  MODULE="src.train_jax_ppo"
fi

if [ "${SMOKE:-0}" = "1" ]; then
  echo "[01_train] SMOKE run (200k steps) via $MODULE"
  python3 -m "$MODULE" --env "$ENV" --seed "$SEED" --num-timesteps 200000 \
    --num-envs "$NUM_ENVS" --iters-per-chunk "$ITERS_PER_CHUNK"
elif [ "$TRAINER" = "brax" ]; then
  echo "[01_train] FULL run via $MODULE"
  python3 -m "$MODULE" --env "$ENV" --seed "$SEED"
else
  # Auto-restart loop: each run trains chunk-by-chunk, checkpointing after every
  # chunk. If the ROCm HSA segfault kills a run mid-training, --resume picks up
  # from the last checkpoint, so total progress accumulates across crashes.
  echo "[01_train] FULL run via $MODULE (envs=$NUM_ENVS chunk=$ITERS_PER_CHUNK, auto-resume)"
  attempt=0
  while [ "$attempt" -le "$MAX_RESTARTS" ]; do
    resume_flag=""
    [ "$attempt" -gt 0 ] && resume_flag="--resume"
    set +e
    python3 -m "$MODULE" --env "$ENV" --seed "$SEED" \
      --num-timesteps "$NUM_TIMESTEPS" --num-envs "$NUM_ENVS" \
      --iters-per-chunk "$ITERS_PER_CHUNK" $resume_flag
    code=$?
    set -e
    if [ "$code" -eq 0 ]; then
      echo "[01_train] training completed (exit 0)"
      break
    fi
    attempt=$((attempt + 1))
    echo "[01_train] run exited $code (likely HSA segfault) — resume attempt $attempt/$MAX_RESTARTS"
    sleep 2
  done
  if [ "$attempt" -gt "$MAX_RESTARTS" ]; then
    echo "[01_train] hit MAX_RESTARTS=$MAX_RESTARTS; latest checkpoint is preserved. Re-run to continue."
    exit 1
  fi
fi
