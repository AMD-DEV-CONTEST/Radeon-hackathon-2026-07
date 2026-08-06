#!/usr/bin/env bash
#
# Reward-profile ablation: baseline / penalty / ttc x N seeds.
#
# Every job trains one policy and then scores it on the canonical baseline
# reward, so runs trained under different shaping schemes stay comparable.
# Jobs run concurrently; per-run steps_per_second is therefore NOT a valid
# throughput measurement -- use the dedicated benchmark for that.
#
# Usage:
#   bash scripts/run_ablation.sh
#   TIMESTEPS=100000 SEEDS="42 43 44 45" bash scripts/run_ablation.sh

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
TIMESTEPS="${TIMESTEPS:-60000}"
N_ENVS="${N_ENVS:-8}"
# The 25->256->256->5 policy is far too small to saturate the GPU, so many
# concurrent jobs serialise on the single HIP context and throughput collapses
# (measured: 85 steps/s aggregate for 9 GPU jobs vs 310 steps/s for one CPU
# job). This study is about reward design, not device performance -- see the
# dedicated ROCm benchmark for the CPU/GPU crossover analysis.
DEVICE="${DEVICE:-cpu}"
SEEDS="${SEEDS:-42 43 44}"
PROFILES="${PROFILES:-baseline penalty ttc}"
EVAL_EPISODES="${EVAL_EPISODES:-30}"
EVAL_SEED="${EVAL_SEED:-100}"

# Keep BLAS from spawning a thread pool per worker; the bottleneck is the
# environment simulation, not linear algebra.
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

LOG_DIR="outputs/logs"
mkdir -p "$LOG_DIR"

echo "=== Reward-profile ablation ==="
echo "profiles:  $PROFILES"
echo "seeds:     $SEEDS"
echo "timesteps: $TIMESTEPS"
echo "n_envs:    $N_ENVS"
echo "device:    $DEVICE"
echo "eval:      $EVAL_EPISODES episodes on the canonical baseline reward"
echo

declare -a PIDS=()
declare -a NAMES=()

for profile in $PROFILES; do
  for seed in $SEEDS; do
    run="abl_${profile}_s${seed}"
    log="${LOG_DIR}/${run}.log"
    echo "launch ${run} -> ${log}"
    (
      "$PYTHON" scripts/02_train_dqn.py \
        --run-name "$run" \
        --reward-profile "$profile" \
        --timesteps "$TIMESTEPS" \
        --n-envs "$N_ENVS" \
        --seed "$seed" \
        --device "$DEVICE" \
        --eval-freq 5000 \
        --eval-episodes 5 \
      && "$PYTHON" scripts/03_evaluate.py \
        --run-name "$run" \
        --episodes "$EVAL_EPISODES" \
        --seed "$EVAL_SEED" \
        --device "$DEVICE"
    ) >"$log" 2>&1 &
    PIDS+=("$!")
    NAMES+=("$run")
  done
done

echo
echo "launched ${#PIDS[@]} jobs, waiting..."

failed=0
for i in "${!PIDS[@]}"; do
  if wait "${PIDS[$i]}"; then
    echo "ok   ${NAMES[$i]}"
  else
    echo "FAIL ${NAMES[$i]}  (see ${LOG_DIR}/${NAMES[$i]}.log)"
    failed=$((failed + 1))
  fi
done

echo
if [ "$failed" -ne 0 ]; then
  echo "$failed job(s) failed."
  exit 1
fi

echo "All jobs finished. Aggregate with:"
echo "  $PYTHON scripts/06_aggregate_ablation.py"
