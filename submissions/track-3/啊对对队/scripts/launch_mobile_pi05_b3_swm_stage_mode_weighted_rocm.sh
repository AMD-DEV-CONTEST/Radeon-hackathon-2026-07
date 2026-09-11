#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
PERSISTENCE_ROOT="${PI05_PERSISTENCE_ROOT:-/workspace/persistence/parcel-sorter-opt-v1}"
DATASET_ROOT="${1:-${ROOT_DIR}/outputs/pi05-b0-absolute-v1-merged}"
OUTPUT_DIR="${2:-${PERSISTENCE_ROOT}/runs/mobile-pi05-b3-swm-stage-mode-weighted-12000-v1}"
LOG_PATH="${3:-${PERSISTENCE_ROOT}/outputs/pi05-b3-swm-stage-mode-weighted-train-v1.log}"
PID_PATH="${LOG_PATH}.pid"
TELEMETRY_DIR="${LOG_PATH%.log}-rocm-telemetry"
DROID_MODEL="${PI05_DROID_MODEL:-/root/pi05-assets/pi05-droid-local}"
STAGE_WEIGHTS="2.035714286,2.035714286,1.221428571,0.407142857,0.610714286,0.407142857"
MODE_FLOW_WEIGHTS="0.7608864696734059,0.920075223319229,1.6697952218430034"
MODE_FLOW_NORMALIZER="1.0014813128091156"

test -f "${DROID_MODEL}/model.safetensors" || {
  echo "ERROR: local PI0.5 DROID bundle is missing: ${DROID_MODEL}" >&2
  exit 2
}
test -f "${DATASET_ROOT}/PI05_ABSOLUTE_DATASET_MANIFEST.json" || {
  echo "ERROR: B3-SWM requires the frozen absolute-action dataset" >&2
  exit 2
}
if [[ -e "${OUTPUT_DIR}" || -e "${LOG_PATH}" || -e "${PID_PATH}" || -e "${TELEMETRY_DIR}" ]]; then
  echo "ERROR: B3-SWM output, log, PID, or telemetry already exists" >&2
  exit 2
fi
if pgrep -f "lerobot_eval.py .*--policy.device=cuda|lerobot_train|train_mobile_pi05_rocm.sh" >/dev/null; then
  echo "ERROR: another PI0.5 GPU task is running; B3-SWM refuses to contend for Radeon" >&2
  exit 3
fi

mkdir -p "${PERSISTENCE_ROOT}/runs" "${PERSISTENCE_ROOT}/outputs" "${PERSISTENCE_ROOT}/artifacts"
nohup env \
  PI05_BASE_MODEL="${DROID_MODEL}" \
  PI05_BASE_REVISION=72824c0a93f00ce5bb8bedb7feb58953ba1da364 \
  MOBILE_PI05_ACTION_CONTRACT=absolute_v1 \
  MOBILE_PI05_STEPS=12000 \
  MOBILE_PI05_SAVE_FREQ=3000 \
  MOBILE_PI05_N_ACTION_STEPS=1 \
  MOBILE_PI05_STATE_TOKEN=1 \
  MOBILE_PI05_MODE_HEAD=1 \
  MOBILE_PI05_MODE_HEAD_POOLING=masked_mean \
  MOBILE_PI05_MODE_HEAD_CE_WEIGHT=2 \
  MOBILE_PI05_MODE_HEAD_CLASS_WEIGHTS="${MODE_FLOW_WEIGHTS}" \
  MOBILE_PI05_STAGE_LOSS_WEIGHTS="${STAGE_WEIGHTS}" \
  MOBILE_PI05_MODE_FLOW_LOSS_WEIGHTS="${MODE_FLOW_WEIGHTS}" \
  MOBILE_PI05_MODE_FLOW_LOSS_NORMALIZER="${MODE_FLOW_NORMALIZER}" \
  MOBILE_PI05_MODE_LOSS_WEIGHT=1 \
  MOBILE_PI05_MODE_CE_WEIGHT=0 \
  MOBILE_PI05_FULL_ACTION_PROJECTIONS=1 \
  MOBILE_PI05_LORA_R=16 \
  MOBILE_PI05_LORA_ALPHA=32 \
  MOBILE_PI05_BATCH_SIZE=1 \
  MOBILE_PI05_NUM_WORKERS=0 \
  /opt/venv/bin/python "${ROOT_DIR}/scripts/run_with_rocm_telemetry.py" \
  --output "${TELEMETRY_DIR}" --interval-seconds 1 -- \
  bash "${ROOT_DIR}/scripts/train_mobile_pi05_rocm.sh" \
  "${DATASET_ROOT}" "${OUTPUT_DIR}" \
  >"${LOG_PATH}" 2>&1 </dev/null &
training_pid=$!
printf '%s\n' "${training_pid}" >"${PID_PATH}"
sleep 2
if ! kill -0 "${training_pid}" 2>/dev/null; then
  echo "ERROR: B3-SWM training exited during launch; inspect ${LOG_PATH}" >&2
  exit 4
fi
printf '{"status":"started","candidate":"B3-SWM","pid":%s,"dataset":"%s","output":"%s","log":"%s","rocm_telemetry":"%s"}\n' \
  "${training_pid}" "${DATASET_ROOT}" "${OUTPUT_DIR}" "${LOG_PATH}" "${TELEMETRY_DIR}"
