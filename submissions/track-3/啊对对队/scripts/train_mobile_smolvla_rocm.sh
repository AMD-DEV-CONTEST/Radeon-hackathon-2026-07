#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:-${ROOT_DIR}/outputs/mobile-bimanual-dataset/lerobot_dataset}"
OUTPUT_DIR="${2:-${ROOT_DIR}/outputs/train/mobile-smolvla-smoke}"
VLM_PATH="${SMOLVLA_VLM_PATH:-${ROOT_DIR}/third_party/models/smolvlm2-500m-video-instruct}"
STEPS="${MOBILE_SMOLVLA_STEPS:-10}"
BATCH_SIZE="${MOBILE_SMOLVLA_BATCH_SIZE:-1}"
NUM_WORKERS="${MOBILE_SMOLVLA_NUM_WORKERS:-0}"
MODALITY="${MOBILE_SMOLVLA_MODALITY:-rgb}"
PROGRESS_CHANNEL="${MOBILE_SMOLVLA_PROGRESS_CHANNEL:-0}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh

test -f "${DATASET_ROOT}/meta/info.json" || {
  echo "ERROR: mobile LeRobotDataset not found: ${DATASET_ROOT}" >&2
  exit 2
}
test -f "${VLM_PATH}/OPEN_SOURCE_MANIFEST.json" || {
  echo "ERROR: audited SmolVLM2 backbone not found: ${VLM_PATH}" >&2
  exit 3
}

# LeRobot 0.6.1 defaults max_state_dim to 32. The audited mobile contract is
# 43-D, so pad to 48 explicitly; 19-D actions fit below max_action_dim=32.
case "${MODALITY}" in
  rgb)
    POLICY_INPUT_FEATURES='{observation.state: {type: STATE, shape: [43]}, observation.images.overhead_rgb: {type: VISUAL, shape: [3, 224, 224]}}'
    ;;
  rgbd)
    POLICY_INPUT_FEATURES='{observation.state: {type: STATE, shape: [43]}, observation.images.overhead_rgb: {type: VISUAL, shape: [3, 224, 224]}, observation.images.overhead_depth_rgb: {type: VISUAL, shape: [3, 224, 224]}}'
    ;;
  *)
    echo "ERROR: MOBILE_SMOLVLA_MODALITY must be rgb or rgbd, received: ${MODALITY}" >&2
    exit 4
    ;;
esac
case "${PROGRESS_CHANNEL}" in
  0)
    POLICY_OUTPUT_FEATURES='{action: {type: ACTION, shape: [19]}}'
    ACTION_CONTRACT="action19"
    ;;
  1)
    POLICY_OUTPUT_FEATURES='{action: {type: ACTION, shape: [20]}}'
    ACTION_CONTRACT="action19-progress1"
    ;;
  *)
    echo "ERROR: MOBILE_SMOLVLA_PROGRESS_CHANNEL must be 0 or 1, received: ${PROGRESS_CHANNEL}" >&2
    exit 5
    ;;
esac

lerobot-train \
  --dataset.repo_id local/mobile-bimanual-parcel-expert \
  --dataset.root "${DATASET_ROOT}" \
  --dataset.depth_output_unit m \
  --dataset.image_transforms.enable false \
  --policy.type smolvla \
  --policy.device cuda \
  --policy.push_to_hub false \
  --policy.use_amp true \
  --policy.vlm_model_name "${VLM_PATH}" \
  --policy.load_vlm_weights true \
  --policy.input_features "${POLICY_INPUT_FEATURES}" \
  --policy.output_features "${POLICY_OUTPUT_FEATURES}" \
  --policy.max_state_dim 48 \
  --policy.max_action_dim 32 \
  --policy.freeze_vision_encoder true \
  --policy.train_expert_only true \
  --policy.chunk_size 30 \
  --policy.n_action_steps 10 \
  --output_dir "${OUTPUT_DIR}" \
  --job_name "mobile-bimanual-smolvla-${MODALITY}-${ACTION_CONTRACT}-rocm" \
  --batch_size "${BATCH_SIZE}" \
  --num_workers "${NUM_WORKERS}" \
  --steps "${STEPS}" \
  --seed 11 \
  --log_freq 1 \
  --save_checkpoint true \
  --save_freq "${STEPS}" \
  --wandb.enable false \
  --env_eval_freq 0 \
  --eval_steps 0
