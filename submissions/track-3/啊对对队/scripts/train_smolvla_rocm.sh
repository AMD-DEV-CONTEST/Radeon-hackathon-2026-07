#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:-${ROOT_DIR}/outputs/radeon-dataset/expert/lerobot_dataset}"
OUTPUT_DIR="${2:-${ROOT_DIR}/outputs/train/smolvla-rocm}"
SPLIT_MANIFEST="${3:-${DATASET_ROOT%/expert/lerobot_dataset}/dataset-split.json}"
VLM_PATH="${SMOLVLA_VLM_PATH:-${ROOT_DIR}/third_party/models/smolvlm2-500m-video-instruct}"
STEPS="${SMOLVLA_STEPS:-4000}"
BATCH_SIZE="${SMOLVLA_BATCH_SIZE:-4}"
NUM_WORKERS="${SMOLVLA_NUM_WORKERS:-4}"
SAVE_FREQ="${SMOLVLA_SAVE_FREQ:-1000}"
FREEZE_VISION="${SMOLVLA_FREEZE_VISION_ENCODER:-true}"
TRAIN_EXPERT_ONLY="${SMOLVLA_TRAIN_EXPERT_ONLY:-true}"
EVAL_STEPS="${SMOLVLA_EVAL_STEPS:-500}"
SEED="${SMOLVLA_SEED:-11}"

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
  echo "ERROR: LeRobot is missing. Run INSTALL_LEROBOT=1 bash scripts/bootstrap_radeon.sh" >&2
  exit 3
fi
if ! python -c "import transformers, num2words" >/dev/null 2>&1; then
  echo "ERROR: LeRobot SmolVLA dependencies are missing." >&2
  echo "Run: INSTALL_LEROBOT=1 bash scripts/bootstrap_radeon.sh" >&2
  exit 4
fi
if [[ ! -f "${SPLIT_MANIFEST}" ]]; then
  echo "ERROR: frozen dataset split not found: ${SPLIT_MANIFEST}" >&2
  exit 5
fi
if [[ ! -f "${VLM_PATH}/OPEN_SOURCE_MANIFEST.json" ]]; then
  echo "ERROR: audited Apache-2.0 SmolVLM2 backbone not found: ${VLM_PATH}" >&2
  echo "Run scripts/stage_open_smolvla_backbone.py before training." >&2
  exit 6
fi

EPISODES="$(python scripts/build_dataset_split.py --manifest "${SPLIT_MANIFEST}" --print episodes)"
EVAL_SPLIT="$(python scripts/build_dataset_split.py --manifest "${SPLIT_MANIFEST}" --print eval_split)"

# Resume uses the checkpoint's complete training configuration. Do not append
# fresh-run policy feature flags here: draccus would treat those serialized
# dictionaries as strings and reject the checkpoint config.
if [[ "${SMOLVLA_RESUME:-false}" == "true" ]]; then
  CONFIG_PATH="${SMOLVLA_CONFIG_PATH:-}"
  if [[ -z "${CONFIG_PATH}" ]]; then
    echo "ERROR: SMOLVLA_CONFIG_PATH is required when SMOLVLA_RESUME=true" >&2
    exit 7
  fi
  lerobot-train \
    --config_path="${CONFIG_PATH}" \
    --resume=true \
    --steps="${STEPS}" \
    --eval_steps="${EVAL_STEPS}" \
    --save_freq="${SAVE_FREQ}" \
    --output_dir="${OUTPUT_DIR}"
  exit $?
fi

# Strict-open initialization uses the Apache-2.0 SmolVLM2 weights and trains the
# SmolVLA action expert. The unlicensed smolvla_base checkpoint is not consumed.
# Inputs are task text, RGB, and non-privileged 20-D state; parcel pose is excluded.
POLICY_INPUT_FEATURES='{observation.state: {type: STATE, shape: [20]}, observation.images.overhead_rgb: {type: VISUAL, shape: [3, 224, 224]}}'
POLICY_OUTPUT_FEATURES='{action: {type: ACTION, shape: [8]}}'
EXTRA_ARGS=()
if [[ -n "${SMOLVLA_EXTRA_ARGS:-}" ]]; then
  read -r -a EXTRA_ARGS <<< "${SMOLVLA_EXTRA_ARGS}"
fi

lerobot-train \
  --dataset.repo_id local/parcel-sorter-expert \
  --dataset.root "${DATASET_ROOT}" \
  --dataset.episodes "${EPISODES}" \
  --dataset.depth_output_unit m \
  --dataset.eval_split "${EVAL_SPLIT}" \
  --dataset.image_transforms.enable false \
  --policy.type smolvla \
  --policy.device cuda \
  --policy.push_to_hub false \
  --policy.use_amp true \
  --policy.vlm_model_name "${VLM_PATH}" \
  --policy.load_vlm_weights true \
  --policy.input_features "${POLICY_INPUT_FEATURES}" \
  --policy.output_features "${POLICY_OUTPUT_FEATURES}" \
  --policy.freeze_vision_encoder "${FREEZE_VISION}" \
  --policy.train_expert_only "${TRAIN_EXPERT_ONLY}" \
  --policy.chunk_size 30 \
  --policy.n_action_steps 10 \
  --output_dir "${OUTPUT_DIR}" \
  --job_name parcel-sorter-smolvla-rocm \
  --batch_size "${BATCH_SIZE}" \
  --num_workers "${NUM_WORKERS}" \
  --steps "${STEPS}" \
  --seed "${SEED}" \
  --log_freq 50 \
  --save_checkpoint true \
  --save_freq "${SAVE_FREQ}" \
  --wandb.enable false \
  --env_eval_freq 0 \
  --eval_steps "${EVAL_STEPS}" \
  "${EXTRA_ARGS[@]}"
