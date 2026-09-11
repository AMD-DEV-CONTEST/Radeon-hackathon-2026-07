#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAIN_PID_PATH="${1:-${ROOT_DIR}/outputs/pi05-b0-absolute-train-v1.log.pid}"
TRAIN_LOG="${2:-${ROOT_DIR}/outputs/pi05-b0-absolute-train-v1.log}"
RUN_ROOT="${3:-/root/pi05-runs/mobile-pi05-b0-absolute-state-token-mode-head-12000-v1}"
DATASET_ROOT="${4:-${ROOT_DIR}/outputs/pi05-b0-absolute-v1-merged}"
OUTPUT_DIR="${5:-${ROOT_DIR}/outputs/pi05-b0-absolute-common-seed-v1}"
POST_LOG="${6:-${ROOT_DIR}/outputs/pi05-b0-absolute-postscreen-v1.log}"
POST_PID_PATH="${POST_LOG}.pid"

if [[ ! -f "${TRAIN_PID_PATH}" ]]; then
  echo "ERROR: training PID file is missing: ${TRAIN_PID_PATH}" >&2
  exit 2
fi
training_pid="$(tr -d '[:space:]' <"${TRAIN_PID_PATH}")"
if [[ ! "${training_pid}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: invalid training PID: ${training_pid}" >&2
  exit 3
fi
if [[ -e "${OUTPUT_DIR}" || -e "${POST_LOG}" || -e "${POST_PID_PATH}" ]]; then
  echo "ERROR: B0 post-screen output, log, or PID file already exists" >&2
  exit 4
fi

nohup bash "${ROOT_DIR}/scripts/postscreen_mobile_pi05_training_rocm.sh" \
  "${training_pid}" "${TRAIN_LOG}" "${RUN_ROOT}" "${DATASET_ROOT}" \
  "${OUTPUT_DIR}" pi05-b0-absolute 3000 6000 9000 12000 \
  >"${POST_LOG}" 2>&1 </dev/null &
post_pid=$!
printf '%s\n' "${post_pid}" >"${POST_PID_PATH}"
sleep 1
if ! kill -0 "${post_pid}" 2>/dev/null; then
  echo "ERROR: B0 post-screen waiter exited during launch" >&2
  exit 5
fi
printf '{"status":"waiting","pid":%s,"training_pid":%s,"output":"%s","log":"%s"}\n' \
  "${post_pid}" "${training_pid}" "${OUTPUT_DIR}" "${POST_LOG}"
