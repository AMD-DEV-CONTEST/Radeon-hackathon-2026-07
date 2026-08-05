#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON_BIN:-python}"
BASE="${TASK3_BASE_MODEL:-$ROOT/outputs/native_lerobot_smolvla_task3_20d_20k/checkpoints/020000/pretrained_model}"
CRITIC="$ROOT/checkpoints/qvgm_critic/task3_native20d20k_q3_rollouts300_calql_v1/checkpoint-final.pt"
RESIDUAL="$ROOT/checkpoints/qvgm_policy/task3_native20d20k_q3_rollouts300_residual_v1/checkpoint-final/pretrained_model"
GRID_DIR="$ROOT/outputs/task3_q3_native20d20k_rollouts300/guidance_grid"
EVAL_ROOT="$ROOT/outputs/task3_q3_native20d20k_rollouts300"
VALIDATION_STATES="40,41,42,43,44,45,46,47,48,49"

export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="${LIBERO_SIM_ROOT:-/path/to/LIBERO-sim}${PYTHONPATH:+:$PYTHONPATH}"
export LIBERO_CONFIG_PATH="${LIBERO_CONFIG_PATH:-$ROOT/configs/libero}"
export MUJOCO_GL="${MUJOCO_GL:-egl}"
export PYOPENGL_PLATFORM="${PYOPENGL_PLATFORM:-egl}"
export SMOLVLA_ATTENTION_BACKEND=sdpa

mkdir -p "$GRID_DIR"
cd "$ROOT"

for required in "$BASE/model.safetensors" "$CRITIC"; do
  [[ -s "$required" ]] || {
    echo "Missing Task 3 evaluation artifact: $required" >&2
    exit 1
  }
done

if [[ ! -s "$GRID_DIR/grid_summary.json" ]]; then
  "$PY" scripts/run_q_guidance_grid.py \
    --cache data/qvgm_buffers/task3_native20d20k_q3_rollouts300_v1/feature_cache.pt \
    --manifest data/qvgm_buffers/task3_native20d20k_q3_rollouts300_v1/feature_cache_manifest.json \
    --checkpoint-glob \
      "checkpoints/qvgm_critic/task3_native20d20k_q3_rollouts300_calql_v1/checkpoint-final.pt" \
    --output-dir "$GRID_DIR" \
    --steps 5,10 \
    --step-sizes 0.005,0.01,0.02 \
    --max-deltas 0.02,0.05 \
    --validation-states "$VALIDATION_STATES" \
    --batch-size 512
fi

common=(
  --states 0-49
  --seeds 2001
  --task-id 3
  --task-suite libero_spatial
  --max-steps 240
  --action-steps 5
)

"$PY" scripts/run_smolvla_libero_sweep.py \
  "${common[@]}" \
  --model-path "$BASE" \
  --output-dir "$EVAL_ROOT/base_seed2001_action5"

"$PY" scripts/run_smolvla_libero_sweep.py \
  "${common[@]}" \
  --model-path "$BASE" \
  --critic-checkpoint "$CRITIC" \
  --critic-mode selection \
  --selection-candidates 4 \
  --output-dir "$EVAL_ROOT/q_selection_n4_seed2001"

# The held-out TD loss is slightly above the predefined gate, so the reported
# replication uses the preregistered conservative preset rather than selecting
# a grid configuration.
"$PY" scripts/run_smolvla_libero_sweep.py \
  "${common[@]}" \
  --model-path "$BASE" \
  --critic-checkpoint "$CRITIC" \
  --critic-mode guidance \
  --guidance-steps 5 \
  --guidance-step-size 0.005 \
  --guidance-max-delta 0.02 \
  --guidance-optimize-prefix-steps 5 \
  --guidance-optimize-action-dims 7 \
  --output-dir "$EVAL_ROOT/q_guidance_seed2001"

if [[ -s "$RESIDUAL/model.safetensors" ]]; then
  "$PY" scripts/run_smolvla_libero_sweep.py \
    "${common[@]}" \
    --model-path "$RESIDUAL" \
    --output-dir "$EVAL_ROOT/qvgm_residual_1000_seed2001"
fi

echo "Task 3 four-way paired evaluation complete."
