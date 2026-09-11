#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:?dataset root is required}"
OUTPUT_DIR="${2:?output directory is required}"
LOG_PATH="${3:?log path is required}"
STEPS="${4:-3000}"
TINY_OVERFIT_GATE="${5:?passed tiny-overfit gate is required}"
WARMUP_STEPS="${6:-0}"

if [[ ! -f "${DATASET_ROOT}/meta/info.json" ]]; then
  echo "ERROR: dataset not found: ${DATASET_ROOT}" >&2
  exit 2
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
  echo "ERROR: output directory already exists: ${OUTPUT_DIR}" >&2
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
nohup env MOBILE_PI05_STEPS="${STEPS}" \
  MOBILE_PI05_TRAINING_ROLE=candidate \
  MOBILE_PI05_ACTION_CONTRACT=absolute_v1 \
  MOBILE_PI05_FULL_ACTION_PROJECTIONS=1 \
  MOBILE_PI05_TINY_OVERFIT_GATE="${TINY_OVERFIT_GATE}" \
  MOBILE_PI05_SCHEDULER_WARMUP_STEPS="${WARMUP_STEPS}" \
  MOBILE_PI05_SCHEDULER_DECAY_STEPS="${STEPS}" \
  PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}" \
  bash "${ROOT_DIR}/scripts/train_mobile_pi05_rocm.sh" \
  "${DATASET_ROOT}" "${OUTPUT_DIR}" \
  >"${LOG_PATH}" 2>&1 </dev/null &
pid=$!
printf '%s\n' "${pid}" >"${LOG_PATH}.pid"

sleep 1
if ! kill -0 "${pid}" 2>/dev/null; then
  echo "ERROR: training process exited during launch" >&2
  tail -n 40 "${LOG_PATH}" >&2 || true
  exit 5
fi

printf '{"pid":%s,"steps":%s,"warmup_steps":%s,"dataset":"%s","output":"%s","log":"%s"}\n' \
  "${pid}" "${STEPS}" "${WARMUP_STEPS}" "${DATASET_ROOT}" "${OUTPUT_DIR}" "${LOG_PATH}"
