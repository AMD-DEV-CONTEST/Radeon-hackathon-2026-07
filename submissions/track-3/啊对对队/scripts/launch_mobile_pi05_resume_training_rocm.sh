#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:?dataset root is required}"
OUTPUT_DIR="${2:?existing output directory is required}"
CHECKPOINT_STEP="${3:?checkpoint step is required}"
LOG_PATH="${4:?new log path is required}"
TOTAL_STEPS="${5:?total target steps are required}"
SAVE_FREQ="${6:-3000}"
RESUME_DECAY_STEPS="${7:-${TOTAL_STEPS}}"
RESUME_WARMUP_STEPS="${8:-0}"
TINY_OVERFIT_GATE="${9:?passed tiny-overfit gate is required}"
PADDED_STEP="$(printf '%06d' "${CHECKPOINT_STEP}")"
RESUME_CONFIG="${OUTPUT_DIR}/checkpoints/${PADDED_STEP}/pretrained_model/train_config.json"
TRAINING_CONTRACT="${OUTPUT_DIR}/PI05_TRAINING_CONTRACT.json"
TRAINING_LAUNCH_AUDIT="${OUTPUT_DIR}/PI05_TRAINING_LAUNCH_AUDIT.json"

if [[ ! -f "${DATASET_ROOT}/meta/info.json" ]]; then
  echo "ERROR: dataset not found: ${DATASET_ROOT}" >&2
  exit 2
fi
if [[ ! -f "${RESUME_CONFIG}" ]]; then
  echo "ERROR: resume config not found: ${RESUME_CONFIG}" >&2
  exit 3
fi
if [[ ! -f "${TRAINING_CONTRACT}" ]]; then
  echo "ERROR: immutable training contract not found: ${TRAINING_CONTRACT}" >&2
  exit 3
fi
if [[ ! -f "${TRAINING_LAUNCH_AUDIT}" ]]; then
  echo "ERROR: original training launch audit not found: ${TRAINING_LAUNCH_AUDIT}" >&2
  exit 3
fi
if [[ -e "${LOG_PATH}" || -e "${LOG_PATH}.pid" ]]; then
  echo "ERROR: log or PID file already exists: ${LOG_PATH}" >&2
  exit 4
fi
if [[ ! -f "${TINY_OVERFIT_GATE}" ]]; then
  echo "ERROR: tiny-overfit gate not found: ${TINY_OVERFIT_GATE}" >&2
  exit 4
fi

mkdir -p "$(dirname "${LOG_PATH}")"
nohup env MOBILE_PI05_STEPS="${TOTAL_STEPS}" \
  MOBILE_PI05_TRAINING_ROLE=candidate \
  MOBILE_PI05_ACTION_CONTRACT=absolute_v1 \
  MOBILE_PI05_FULL_ACTION_PROJECTIONS=1 \
  MOBILE_PI05_TINY_OVERFIT_GATE="${TINY_OVERFIT_GATE}" \
  MOBILE_PI05_SCHEDULER_DECAY_STEPS="${RESUME_DECAY_STEPS}" \
  MOBILE_PI05_SCHEDULER_WARMUP_STEPS="${RESUME_WARMUP_STEPS}" \
  MOBILE_PI05_SAVE_FREQ="${SAVE_FREQ}" \
  MOBILE_PI05_RESUME_CONFIG="${RESUME_CONFIG}" \
  MOBILE_PI05_RESUME_CHECKPOINT_STEP="${CHECKPOINT_STEP}" \
  MOBILE_PI05_RESUME_DECAY_STEPS="${RESUME_DECAY_STEPS}" \
  MOBILE_PI05_RESUME_WARMUP_STEPS="${RESUME_WARMUP_STEPS}" \
  PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}" \
  bash "${ROOT_DIR}/scripts/train_mobile_pi05_rocm.sh" \
  "${DATASET_ROOT}" "${OUTPUT_DIR}" \
  >"${LOG_PATH}" 2>&1 </dev/null &
pid=$!
printf '%s\n' "${pid}" >"${LOG_PATH}.pid"

sleep 1
if ! kill -0 "${pid}" 2>/dev/null; then
  echo "ERROR: resumed training process exited during launch" >&2
  tail -n 40 "${LOG_PATH}" >&2 || true
  exit 5
fi

printf '{"pid":%s,"resume_step":%s,"total_steps":%s,"scheduler_decay_steps":%s,"scheduler_warmup_steps":%s,"output":"%s","log":"%s"}\n' \
  "${pid}" "${CHECKPOINT_STEP}" "${TOTAL_STEPS}" "${RESUME_DECAY_STEPS}" \
  "${RESUME_WARMUP_STEPS}" "${OUTPUT_DIR}" "${LOG_PATH}"
