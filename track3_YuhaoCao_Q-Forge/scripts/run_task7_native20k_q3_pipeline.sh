#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/QVGM"
PY="$ROOT/.venv-rocm/bin/python"
MODEL="$ROOT/outputs/native_lerobot_smolvla_task7_50ep_20k/checkpoints/020000/pretrained_model"
ROLLOUTS="$ROOT/data/collected_pickle/task7_native20k_rollouts50_q3_v1"
BUFFER="$ROOT/data/qvgm_buffers/task7_native20k_q3_v1"
MC="$ROOT/checkpoints/qvgm_critic/task7_native20k_q3_mc_v1"
CRITIC="$ROOT/checkpoints/qvgm_critic/task7_native20k_q3_calql_v1"
GRID="$ROOT/outputs/task7_q3_native20k/guidance_grid"
RESIDUAL="$ROOT/checkpoints/qvgm_policy/task7_native20k_q3_residual_v1"
EVAL="$ROOT/outputs/task7_q3_native20k"
LOG="$ROOT/outputs/logs/task7_native20k_q3_pipeline.log"
COLLECT_PID_FILE="$ROOT/outputs/logs/task7_native20k_rollouts50_q3_v1.pid"
VALIDATION_STATES="40,41,42,43,44,45,46,47,48,49"

export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="/workspace/LIBERO-sim${PYTHONPATH:+:$PYTHONPATH}"
export LIBERO_CONFIG_PATH="$ROOT/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
# Force PyTorch SDPA's math backend; the vendored SmolVLA implementation reads
# this selector and will not dispatch attention to FlashAttention.
export SMOLVLA_ATTENTION_BACKEND=sdpa

mkdir -p "$BUFFER" "$MC" "$CRITIC" "$GRID" "$EVAL" "$ROOT/outputs/logs"
exec >>"$LOG" 2>&1
echo "$(date -u +%FT%TZ) q3 pipeline waiting for exact 50-rollout collection"

while true; do
  count=$(find "$ROLLOUTS" -maxdepth 1 -name '*.pkl' 2>/dev/null | wc -l)
  if [[ "$count" -eq 50 ]]; then
    break
  fi
  if [[ -s "$COLLECT_PID_FILE" ]]; then
    collect_pid=$(cat "$COLLECT_PID_FILE")
    if ! kill -0 "$collect_pid" 2>/dev/null; then
      echo "collection exited at $count/50" >&2
      exit 1
    fi
  fi
  sleep 30
done

"$PY" "$ROOT/scripts/validate_task7_rollouts50.py" "$ROLLOUTS" \
  --output "$ROLLOUTS/rollout_manifest.json"
echo "$(date -u +%FT%TZ) rollout validation complete"

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
    --checkpoint-glob 'checkpoints/qvgm_critic/task7_native20k_q3_calql_v1/checkpoint-final.pt' \
    --output-dir "$GRID" --steps 5,10 --step-sizes 0.005,0.01,0.02 \
    --max-deltas 0.02,0.05 --validation-states "$VALIDATION_STATES" \
    --batch-size 512
fi

if [[ ! -s "$RESIDUAL/checkpoint-final/pretrained_model/model.safetensors" ]]; then
  cd "$ROOT"
  "$PY" scripts/train_qvgm_residual_velocity.py \
    --config configs/experiments/task7_native20k_q3_residual.yaml
fi

read -r guidance_steps guidance_lr guidance_delta < <(
  "$PY" - "$GRID" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
summary = json.loads((root / "grid_summary.json").read_text())
tags = summary["ranked_eligible_tags"]
if not tags:
    raise SystemExit("no guidance configuration passed the offline gates")
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

echo "$(date -u +%FT%TZ) q3 pipeline complete"
