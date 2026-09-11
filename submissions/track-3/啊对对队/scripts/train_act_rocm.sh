#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:-${ROOT_DIR}/outputs/radeon-dataset/expert/lerobot_dataset}"
OUTPUT_DIR="${2:-${ROOT_DIR}/outputs/train/act-rocm}"
STEPS="${ACT_STEPS:-100000}"
SEED="${ACT_SEED:-42}"
BATCH_SIZE="${ACT_BATCH_SIZE:-32}"
NUM_WORKERS="${ACT_NUM_WORKERS:-4}"
SAVE_FREQ="${ACT_SAVE_FREQ:-20000}"
SAVE_CHECKPOINT="${ACT_SAVE_CHECKPOINT:-true}"
LOG_FREQ="${ACT_LOG_FREQ:-100}"
USE_AMP="${ACT_USE_AMP:-false}"
IMAGE_TRANSFORMS="${ACT_IMAGE_TRANSFORMS:-false}"
PRETRAINED_BACKBONE="${ACT_PRETRAINED_BACKBONE:-imagenet}"
EVAL_SPLIT="${ACT_EVAL_SPLIT:-0.1}"
EVAL_STEPS="${ACT_EVAL_STEPS:-1000}"
CHUNK_SIZE="${ACT_CHUNK_SIZE:-30}"
N_ACTION_STEPS="${ACT_N_ACTION_STEPS:-10}"
DIM_MODEL="${ACT_DIM_MODEL:-512}"
N_ENCODER_LAYERS="${ACT_N_ENCODER_LAYERS:-4}"
N_DECODER_LAYERS="${ACT_N_DECODER_LAYERS:-1}"
TEMPORAL_ENSEMBLE_COEFF="${ACT_TEMPORAL_ENSEMBLE_COEFF:-}"
USE_DEPTH="${ACT_USE_DEPTH:-false}"
SPLIT_MANIFEST="${DATASET_SPLIT_MANIFEST:-}"

if [[ -z "${SPLIT_MANIFEST}" && "${EVAL_SPLIT}" =~ ^0([.]0+)?$ && "${EVAL_STEPS}" != "0" ]]; then
  echo "ERROR: ACT_EVAL_STEPS must be 0 when ACT_EVAL_SPLIT is 0" >&2
  exit 7
fi

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh

if [[ ! -f "${DATASET_ROOT}/meta/info.json" ]]; then
  echo "ERROR: LeRobotDataset not found: ${DATASET_ROOT}" >&2
  exit 2
fi
if ! command -v lerobot-train >/dev/null 2>&1; then
  echo "ERROR: LeRobot training dependencies are missing." >&2
  echo "Run: INSTALL_LEROBOT=1 bash scripts/bootstrap_radeon.sh" >&2
  exit 3
fi

# Do not expose observation.privileged_state (parcel ground truth) to the policy.
AUDIT_ARGS=(--dataset-root "${DATASET_ROOT}")
DATASET_ARGS=(--dataset.eval_split "${EVAL_SPLIT}")
if [[ -n "${SPLIT_MANIFEST}" ]]; then
  if [[ ! -f "${SPLIT_MANIFEST}" ]]; then
    echo "ERROR: dataset split manifest not found: ${SPLIT_MANIFEST}" >&2
    exit 9
  fi
  SPLIT_EPISODES="$(python scripts/build_dataset_split.py --manifest "${SPLIT_MANIFEST}" --print episodes)"
  SPLIT_EVAL="$(python scripts/build_dataset_split.py --manifest "${SPLIT_MANIFEST}" --print eval_split)"
  if [[ "${SPLIT_EVAL}" == "0" && "${EVAL_STEPS}" != "0" ]]; then
    echo "ERROR: ACT_EVAL_STEPS must be 0 when the split has no validation episodes" >&2
    exit 10
  fi
  DATASET_ARGS=(--dataset.episodes "${SPLIT_EPISODES}" --dataset.eval_split "${SPLIT_EVAL}")
fi
POLICY_INPUT_FEATURES='{observation.state: {type: STATE, shape: [20]}, observation.images.overhead_rgb: {type: VISUAL, shape: [3, 224, 224]}}'
if [[ "${USE_DEPTH}" == "true" ]]; then
  AUDIT_ARGS+=(--require-depth-rgb)
  POLICY_INPUT_FEATURES='{observation.state: {type: STATE, shape: [20]}, observation.images.overhead_rgb: {type: VISUAL, shape: [3, 224, 224]}, observation.images.overhead_depth_rgb: {type: VISUAL, shape: [3, 224, 224]}}'
elif [[ "${USE_DEPTH}" != "false" ]]; then
  echo "ERROR: ACT_USE_DEPTH must be true or false" >&2
  exit 6
fi
python scripts/audit_dataset.py "${AUDIT_ARGS[@]}"
TRAIN_ARGS=(
  --dataset.repo_id local/parcel-sorter-expert
  --dataset.root "${DATASET_ROOT}"
  --dataset.depth_output_unit m
  "${DATASET_ARGS[@]}"
  --dataset.image_transforms.enable "${IMAGE_TRANSFORMS}"
  --policy.type act
  --policy.device cuda
  --policy.push_to_hub false
  --policy.use_amp "${USE_AMP}"
  --policy.input_features "${POLICY_INPUT_FEATURES}"
  --policy.chunk_size "${CHUNK_SIZE}"
  --policy.n_action_steps "${N_ACTION_STEPS}"
  --policy.dim_model "${DIM_MODEL}"
  --policy.n_encoder_layers "${N_ENCODER_LAYERS}"
  --policy.n_decoder_layers "${N_DECODER_LAYERS}"
  --seed "${SEED}"
  --output_dir "${OUTPUT_DIR}"
  --job_name parcel-sorter-act-rocm
  --batch_size "${BATCH_SIZE}"
  --num_workers "${NUM_WORKERS}"
  --steps "${STEPS}"
  --log_freq "${LOG_FREQ}"
  --save_checkpoint "${SAVE_CHECKPOINT}"
  --save_freq "${SAVE_FREQ}"
  --wandb.enable false
  --env_eval_freq 0
  --eval_steps "${EVAL_STEPS}"
)

if [[ "${NUM_WORKERS}" == "0" ]]; then
  TRAIN_ARGS+=(--persistent_workers false)
fi
if [[ "${PRETRAINED_BACKBONE}" == "none" ]]; then
  TRAIN_ARGS+=(--policy.pretrained_backbone_weights null)
fi
if [[ -n "${TEMPORAL_ENSEMBLE_COEFF}" ]]; then
  if [[ "${N_ACTION_STEPS}" != "1" ]]; then
    echo "ERROR: ACT_TEMPORAL_ENSEMBLE_COEFF requires ACT_N_ACTION_STEPS=1 in LeRobot 0.6.1" >&2
    exit 5
  fi
  TRAIN_ARGS+=(--policy.temporal_ensemble_coeff "${TEMPORAL_ENSEMBLE_COEFF}")
fi

lerobot-train "${TRAIN_ARGS[@]}"
