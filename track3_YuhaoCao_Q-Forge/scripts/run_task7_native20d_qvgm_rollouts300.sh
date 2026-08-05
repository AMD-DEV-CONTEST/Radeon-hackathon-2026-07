#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/QVGM"
PY="$ROOT/.venv-rocm/bin/python"
MODEL="$ROOT/outputs/native_lerobot_smolvla_task7_20d_20k/checkpoints/020000/pretrained_model"
ROLLOUTS="$ROOT/data/collected_pickle/task7_native20d20k_rollouts300_perturbed_v1"
BUFFER="$ROOT/data/qvgm_buffers/task7_native20d20k_q3_rollouts300_v1"
MC="$ROOT/checkpoints/qvgm_critic/task7_native20d20k_q3_rollouts300_mc_v1"
CRITIC="$ROOT/checkpoints/qvgm_critic/task7_native20d20k_q3_rollouts300_calql_v1"
RESIDUAL="$ROOT/checkpoints/qvgm_policy/task7_native20d20k_q3_rollouts300_residual_v1"
EVAL="$ROOT/outputs/task7_q3_native20d20k_rollouts300/qvgm_residual_1000_seed2001"
LOG="$ROOT/outputs/logs/task7_native20d_qvgm_rollouts300_pipeline.log"
FAILURE_STATES="0-49"
VALIDATION_STATES="40,41,42,43,44,45,46,47,48,49"

export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="/workspace/LIBERO-sim${PYTHONPATH:+:$PYTHONPATH}"
export LIBERO_CONFIG_PATH="$ROOT/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl

mkdir -p "$ROLLOUTS" "$BUFFER" "$MC" "$CRITIC" "$RESIDUAL" "$EVAL" "$ROOT/outputs/logs"
exec >>"$LOG" 2>&1
echo "$(date -u +%FT%TZ) starting 20D simple-QVGM 300-rollout pipeline"

for required in "$MODEL/model.safetensors" "$MODEL/config.json"; do
  [[ -s "$required" ]] || { echo "missing 20D Base artifact: $required" >&2; exit 1; }
done

export SMOLVLA_ATTENTION_BACKEND=eager
cd "$ROOT"
collection_pids=()
for worker_id in 0 1; do
  "$PY" scripts/collect_task7_critic_diverse.py \
    --model-path "$MODEL" \
    --output-dir "$ROLLOUTS" \
    --states 0-49 \
    --failure-states "$FAILURE_STATES" \
    --perturb-probability 0.5 \
    --action-steps 5 \
    --max-steps 240 \
    --seed 3300 \
    --worker-id "$worker_id" \
    --num-workers 2 \
    >"$ROOT/outputs/logs/task7_native20d_rollouts300_worker${worker_id}.log" 2>&1 &
  collection_pids+=("$!")
done
for collection_pid in "${collection_pids[@]}"; do
  wait "$collection_pid"
done

"$PY" scripts/summarize_diverse_collection.py \
  --pickle-dir "$ROLLOUTS" \
  --output "$ROLLOUTS/rollout_manifest.json" \
  --states 0-49 \
  --failure-states "$FAILURE_STATES"

"$PY" - "$ROLLOUTS/rollout_manifest.json" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert manifest["episodes"] == 300, manifest["episodes"]
assert manifest["state_count"] == 50, manifest["state_count"]
assert manifest["states"] == list(range(50)), manifest["states"]
assert manifest["plan_complete"] is True
assert manifest["perturbed_steps"] > 0
print("validated exact 300-rollout perturbed collection", flush=True)
PY

if [[ ! -s "$BUFFER/feature_cache.pt" ]]; then
  "$PY" scripts/cache_qvgm_features.py \
    --pickle-dir "$ROLLOUTS" \
    --output-dir "$BUFFER" \
    --model-path "$MODEL" \
    --horizon 5 \
    --gamma 0.99 \
    --feature-dim 512 \
    --projection-seed 1000 \
    --batch-size 8
fi

if [[ ! -s "$BUFFER/policy_observations.pt" ]]; then
  "$PY" scripts/cache_qvgm_policy_observations.py \
    --feature-cache "$BUFFER/feature_cache.pt" \
    --feature-manifest "$BUFFER/feature_cache_manifest.json" \
    --output-dir "$BUFFER"
fi

if [[ ! -s "$MC/checkpoint-final.pt" ]]; then
  "$PY" scripts/train_qvgm_critic_mc.py \
    --cache "$BUFFER/feature_cache.pt" \
    --manifest "$BUFFER/feature_cache_manifest.json" \
    --output-dir "$MC" \
    --steps 5000 \
    --batch-size 256 \
    --learning-rate 3e-4 \
    --weight-decay 1e-4 \
    --hidden-dim 512 \
    --first-hidden-dim 1024 \
    --proprio-feature-dim 256 \
    --ensemble-size 5 \
    --validation-states "$VALIDATION_STATES" \
    --seed 1000
fi

if [[ ! -s "$CRITIC/checkpoint-final.pt" ]]; then
  "$PY" scripts/train_qvgm_critic_td.py \
    --cache "$BUFFER/feature_cache.pt" \
    --manifest "$BUFFER/feature_cache_manifest.json" \
    --init-checkpoint "$MC/checkpoint-final.pt" \
    --output-dir "$CRITIC" \
    --next-action-source dataset \
    --steps 2000 \
    --batch-size 256 \
    --learning-rate 1e-4 \
    --tau 0.005 \
    --cql-alpha 0.05 \
    --cql-random-actions 10 \
    --cql-reference-noise-std 0.05 \
    --calql \
    --validation-states "$VALIDATION_STATES" \
    --seed 1000
fi

export SMOLVLA_ATTENTION_BACKEND=sdpa
if [[ ! -s "$RESIDUAL/checkpoint-final/pretrained_model/model.safetensors" ]]; then
  "$PY" scripts/train_qvgm_residual_velocity.py \
    --config configs/experiments/task7_native20d20k_q3_rollouts300_residual.yaml
fi

if [[ ! -s "$EVAL/summary.json" ]]; then
  "$PY" scripts/run_smolvla_libero_sweep.py \
    --states 0-49 \
    --seeds 2001 \
    --task-id 7 \
    --task-suite libero_spatial \
    --max-steps 240 \
    --action-steps 5 \
    --model-path "$RESIDUAL/checkpoint-final/pretrained_model" \
    --output-dir "$EVAL"
fi

echo "$(date -u +%FT%TZ) 20D simple-QVGM 300-rollout pipeline complete"
