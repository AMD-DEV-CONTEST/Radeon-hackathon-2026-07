#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/QVGM"
PY="$ROOT/.venv-rocm/bin/python"
SOURCE_BUFFER="$ROOT/data/qvgm_buffers/task7_native20d20k_q3_rollouts300_v1"
BUFFER="$ROOT/data/qvgm_buffers/task7_native20d20k_q3_rollouts50_perturbed_v1"
MC="$ROOT/checkpoints/qvgm_critic/task7_native20d20k_q3_rollouts50_perturbed_mc_v1"
CRITIC="$ROOT/checkpoints/qvgm_critic/task7_native20d20k_q3_rollouts50_perturbed_calql_v1"
RESIDUAL="$ROOT/checkpoints/qvgm_policy/task7_native20d20k_q3_rollouts50_perturbed_residual_v1"
EVAL="$ROOT/outputs/task7_q3_native20d20k_rollouts50_perturbed/qvgm_residual_1000_seed2001"
LOG="$ROOT/outputs/logs/task7_native20d_qvgm_rollouts50_perturbed_pipeline.log"
VALIDATION_STATES="40,41,42,43,44,45,46,47,48,49"

export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="/workspace/LIBERO-sim${PYTHONPATH:+:$PYTHONPATH}"
export LIBERO_CONFIG_PATH="$ROOT/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl

mkdir -p "$BUFFER" "$MC" "$CRITIC" "$RESIDUAL" "$EVAL" "$ROOT/outputs/logs"
exec >>"$LOG" 2>&1
echo "$(date -u +%FT%TZ) starting 20D simple-QVGM 50-perturbed-rollout ablation"

if [[ ! -s "$BUFFER/feature_cache.pt" ]]; then
  "$PY" scripts/subset_qvgm_cache_by_repeat.py \
    --source-dir "$SOURCE_BUFFER" \
    --output-dir "$BUFFER" \
    --repeat-id 2
fi

"$PY" - "$BUFFER" <<'PY'
import json
import pathlib
import sys
import torch

root = pathlib.Path(sys.argv[1])
feature_manifest = json.loads((root / "feature_cache_manifest.json").read_text())
observation_manifest = json.loads(
    (root / "policy_observations_manifest.json").read_text()
)
features = torch.load(
    root / "feature_cache.pt", map_location="cpu", weights_only=True, mmap=True
)
observations = torch.load(
    root / "policy_observations.pt", map_location="cpu", weights_only=True, mmap=True
)
assert len(feature_manifest["episodes"]) == 50
assert len(observation_manifest["episodes"]) == 50
assert feature_manifest["transitions"] == 10254
assert observation_manifest["transitions"] == 10254
assert sorted(
    int(row["task_reset_state_id"]) for row in feature_manifest["episodes"]
) == list(range(50))
assert all(int(row["repeat_id"]) == 2 for row in feature_manifest["episodes"])
assert all(float(row["planned_perturbation_sigma"]) == 0.03 for row in feature_manifest["episodes"])
assert sum(int(row["perturbed_action_steps"]) for row in feature_manifest["episodes"]) == 5094
assert torch.equal(observations["states"].float(), features["proprio"].float())
print("validated exact 50-rollout sigma=0.03 cache subset", flush=True)
PY

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
    --config configs/experiments/task7_native20d20k_q3_rollouts50_perturbed_residual.yaml
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

echo "$(date -u +%FT%TZ) 20D simple-QVGM 50-perturbed-rollout ablation complete"
