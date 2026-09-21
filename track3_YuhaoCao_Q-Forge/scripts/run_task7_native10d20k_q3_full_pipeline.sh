#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/QVGM"
PY="$ROOT/.venv-rocm/bin/python"
TRAIN_PID_FILE="$ROOT/outputs/logs/native_lerobot_smolvla_task7_10d_20k.pid"
TRAIN_LOG="$ROOT/outputs/logs/native_lerobot_smolvla_task7_10d_20k.log"
MODEL="$ROOT/outputs/native_lerobot_smolvla_task7_10d_20k/checkpoints/020000/pretrained_model"
ROLLOUTS="$ROOT/data/collected_pickle/task7_native10d20k_rollouts50_q3_v1"
BUFFER="$ROOT/data/qvgm_buffers/task7_native10d20k_q3_v1"
MC="$ROOT/checkpoints/qvgm_critic/task7_native10d20k_q3_mc_v1"
CRITIC="$ROOT/checkpoints/qvgm_critic/task7_native10d20k_q3_calql_v1"
GRID="$ROOT/outputs/task7_q3_native10d20k/guidance_grid"
RESIDUAL="$ROOT/checkpoints/qvgm_policy/task7_native10d20k_q3_residual_v1"
EVAL="$ROOT/outputs/task7_q3_native10d20k"
LOG="$ROOT/outputs/logs/task7_native10d20k_q3_full_pipeline.log"
VALIDATION_STATES="40,41,42,43,44,45,46,47,48,49"

export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="/workspace/LIBERO-sim${PYTHONPATH:+:$PYTHONPATH}"
export LIBERO_CONFIG_PATH="$ROOT/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl

mkdir -p "$ROLLOUTS" "$BUFFER" "$MC" "$CRITIC" "$GRID" "$EVAL" "$ROOT/outputs/logs"
exec >>"$LOG" 2>&1
echo "$(date -u +%FT%TZ) 10D full pipeline waiting for native SFT"

train_pid=$(cat "$TRAIN_PID_FILE")
while kill -0 "$train_pid" 2>/dev/null; do
  sleep 60
done
if ! grep -q 'End of training' "$TRAIN_LOG"; then
  echo "10D native SFT exited without End of training" >&2
  exit 1
fi
for required in \
  "$MODEL/model.safetensors" \
  "$MODEL/config.json" \
  "$ROOT/outputs/native_lerobot_smolvla_task7_10d_20k/checkpoints/020000/training_state/training_step.json"; do
  [[ -s "$required" ]] || { echo "missing SFT artifact: $required" >&2; exit 1; }
done
echo "$(date -u +%FT%TZ) 10D native SFT validated"

# Match the completed 50D experiment: rollout/cache/critic use the original
# eager attention implementation; residual training and final four-way eval
# use the user-requested PyTorch SDPA math backend.
export SMOLVLA_ATTENTION_BACKEND=eager
count=$(find "$ROLLOUTS" -maxdepth 1 -name '*.pkl' 2>/dev/null | wc -l)
if [[ "$count" -lt 50 ]]; then
  cd "$ROOT"
  "$PY" scripts/collect_libero_suite_critic_rollouts.py \
    --suite libero_spatial --task-ids 7 --states 0-49 \
    --repeats 1 --expected-total 50 --model-path "$MODEL" \
    --output-dir "$ROLLOUTS" --action-steps 5 --max-steps 240 --seed 3000
fi
"$PY" "$ROOT/scripts/validate_task7_rollouts50.py" "$ROLLOUTS" \
  --output "$ROLLOUTS/rollout_manifest.json"

if [[ ! -s "$BUFFER/feature_cache.pt" ]]; then
  "$PY" "$ROOT/scripts/cache_qvgm_features.py" \
    --pickle-dir "$ROLLOUTS" --output-dir "$BUFFER" \
    --model-path "$MODEL" --horizon 5 --gamma 0.99 \
    --feature-dim 512 --projection-seed 1000 --batch-size 8
fi
if [[ ! -s "$BUFFER/policy_observations.pt" ]]; then
  "$PY" "$ROOT/scripts/cache_qvgm_policy_observations.py" \
    --feature-cache "$BUFFER/feature_cache.pt" \
    --feature-manifest "$BUFFER/feature_cache_manifest.json" \
    --output-dir "$BUFFER"
fi
if [[ ! -s "$MC/checkpoint-final.pt" ]]; then
  "$PY" "$ROOT/scripts/train_qvgm_critic_mc.py" \
    --cache "$BUFFER/feature_cache.pt" \
    --manifest "$BUFFER/feature_cache_manifest.json" \
    --output-dir "$MC" --steps 5000 --batch-size 256 \
    --learning-rate 3e-4 --weight-decay 1e-4 \
    --hidden-dim 512 --first-hidden-dim 1024 --proprio-feature-dim 256 \
    --ensemble-size 5 --validation-states "$VALIDATION_STATES" --seed 1000
fi
if [[ ! -s "$CRITIC/checkpoint-final.pt" ]]; then
  "$PY" "$ROOT/scripts/train_qvgm_critic_td.py" \
    --cache "$BUFFER/feature_cache.pt" \
    --manifest "$BUFFER/feature_cache_manifest.json" \
    --init-checkpoint "$MC/checkpoint-final.pt" \
    --output-dir "$CRITIC" --next-action-source dataset \
    --steps 2000 --batch-size 256 --learning-rate 1e-4 --tau 0.005 \
    --cql-alpha 0.05 --cql-random-actions 10 \
    --cql-reference-noise-std 0.05 --calql \
    --validation-states "$VALIDATION_STATES" --seed 1000
fi
if [[ ! -s "$GRID/grid_summary.json" ]]; then
  cd "$ROOT"
  "$PY" scripts/run_q_guidance_grid.py \
    --cache "$BUFFER/feature_cache.pt" \
    --manifest "$BUFFER/feature_cache_manifest.json" \
    --checkpoint-glob \
      'checkpoints/qvgm_critic/task7_native10d20k_q3_calql_v1/checkpoint-final.pt' \
    --output-dir "$GRID" --steps 5,10 --step-sizes 0.005,0.01,0.02 \
    --max-deltas 0.02,0.05 --validation-states "$VALIDATION_STATES" \
    --batch-size 512
fi

export SMOLVLA_ATTENTION_BACKEND=sdpa
if [[ ! -s "$RESIDUAL/checkpoint-final/pretrained_model/model.safetensors" ]]; then
  cd "$ROOT"
  "$PY" scripts/train_qvgm_residual_velocity.py \
    --config configs/experiments/task7_native10d20k_q3_residual.yaml
fi

read -r guidance_steps guidance_lr guidance_delta < <(
  "$PY" - "$GRID" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
summary = json.loads((root / "grid_summary.json").read_text())
tags = summary["ranked_eligible_tags"]
if not tags:
    # Do not relax or silently rewrite the registered critic gate.  Complete
    # the requested diagnostic sweep with the predeclared conservative setting
    # and retain the gate failure in grid_summary.json and the final report.
    tags = ["task7_native10d20k_q3_calql_v1_s5_lr0.005_d0.02"]
record = json.loads((root / f"{tags[0]}.json").read_text())
g = record["guidance"]
print(g["steps"], g["step_size"], g["max_delta"])
PY
)
echo "selected guidance: steps=$guidance_steps lr=$guidance_lr delta=$guidance_delta"

run_eval() {
  local output="$1"
  shift
  if [[ ! -s "$output/summary.json" ]]; then
    cd "$ROOT"
    "$PY" scripts/run_smolvla_libero_sweep.py \
      --states 0-49 --seeds 2001 --task-id 7 --task-suite libero_spatial \
      --max-steps 240 --action-steps 5 --output-dir "$output" "$@"
  fi
}

run_eval "$EVAL/base_seed2001_action5" --model-path "$MODEL"
run_eval "$EVAL/q_selection_n4_seed2001" \
  --model-path "$MODEL" --critic-checkpoint "$CRITIC/checkpoint-final.pt" \
  --critic-mode selection --selection-candidates 4
run_eval "$EVAL/q_guidance_seed2001" \
  --model-path "$MODEL" --critic-checkpoint "$CRITIC/checkpoint-final.pt" \
  --critic-mode guidance --guidance-steps "$guidance_steps" \
  --guidance-step-size "$guidance_lr" --guidance-max-delta "$guidance_delta" \
  --guidance-optimize-prefix-steps 5 --guidance-optimize-action-dims 7
run_eval "$EVAL/qvgm_residual_seed2001" \
  --model-path "$RESIDUAL/checkpoint-final/pretrained_model"

echo "$(date -u +%FT%TZ) 10D q3 full pipeline complete"
