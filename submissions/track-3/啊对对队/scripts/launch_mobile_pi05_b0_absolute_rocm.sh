#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:-${ROOT_DIR}/outputs/pi05-b0-absolute-v1-merged}"
OUTPUT_DIR="${2:-/root/pi05-runs/mobile-pi05-b0-absolute-state-token-mode-head-12000-v1}"
LOG_PATH="${3:-${ROOT_DIR}/outputs/pi05-b0-absolute-train-v1.log}"
PID_PATH="${LOG_PATH}.pid"

if [[ -e "${OUTPUT_DIR}" ]]; then
  echo "ERROR: B0 output already exists: ${OUTPUT_DIR}" >&2
  exit 2
fi
if [[ -e "${LOG_PATH}" || -e "${PID_PATH}" ]]; then
  echo "ERROR: B0 log or PID file already exists" >&2
  exit 3
fi
if pgrep -f "train_mobile_pi05_rocm.sh.*${DATASET_ROOT}" >/dev/null; then
  echo "ERROR: a PI0.5 training process already uses this dataset" >&2
  exit 4
fi

mkdir -p "$(dirname "${LOG_PATH}")"
nohup env \
  MOBILE_PI05_ACTION_CONTRACT=absolute_v1 \
  MOBILE_PI05_STEPS=12000 \
  MOBILE_PI05_SAVE_FREQ=3000 \
  MOBILE_PI05_N_ACTION_STEPS=1 \
  MOBILE_PI05_STATE_TOKEN=1 \
  MOBILE_PI05_MODE_HEAD=1 \
  MOBILE_PI05_MODE_HEAD_POOLING=masked_mean \
  MOBILE_PI05_MODE_HEAD_CE_WEIGHT=2 \
  MOBILE_PI05_MODE_HEAD_CLASS_WEIGHTS=0.7608864696734059,0.920075223319229,1.6697952218430034 \
  MOBILE_PI05_MODE_LOSS_WEIGHT=1 \
  MOBILE_PI05_MODE_CE_WEIGHT=0 \
  MOBILE_PI05_BATCH_SIZE=1 \
  MOBILE_PI05_NUM_WORKERS=0 \
  bash "${ROOT_DIR}/scripts/train_mobile_pi05_rocm.sh" \
  "${DATASET_ROOT}" "${OUTPUT_DIR}" \
  >"${LOG_PATH}" 2>&1 </dev/null &
training_pid=$!
printf '%s\n' "${training_pid}" >"${PID_PATH}"
sleep 2
if ! kill -0 "${training_pid}" 2>/dev/null; then
  echo "ERROR: B0 training exited during launch; inspect ${LOG_PATH}" >&2
  exit 5
fi
printf '{"status":"started","pid":%s,"dataset":"%s","output":"%s","log":"%s"}\n' \
  "${training_pid}" "${DATASET_ROOT}" "${OUTPUT_DIR}" "${LOG_PATH}"
