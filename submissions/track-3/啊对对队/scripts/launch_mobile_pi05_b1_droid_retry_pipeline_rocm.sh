#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${ROOT_DIR}/outputs/pi05-b0-absolute-v1-merged"
RUN_ROOT="/root/pi05-runs/mobile-pi05-b1-droid-absolute-12000-v2"
TRAIN_LOG="${ROOT_DIR}/outputs/pi05-b1-droid-absolute-train-v2.log"
SCREEN_ROOT="${ROOT_DIR}/outputs/pi05-b1-droid-absolute-common-seed-v2"
POST_LOG="${ROOT_DIR}/outputs/pi05-b1-droid-absolute-postscreen-v2.log"
STRICT_ROOT="${ROOT_DIR}/outputs/pi05-b1-droid-absolute-strict-dev-v2"
AUTO_LOG="${ROOT_DIR}/outputs/pi05-b1-droid-absolute-strict-auto-v2.log"

bash "${ROOT_DIR}/scripts/launch_mobile_pi05_b1_droid_absolute_rocm.sh" \
  "${DATASET_ROOT}" "${RUN_ROOT}" "${TRAIN_LOG}"
train_pid="$(tr -d '[:space:]' <"${TRAIN_LOG}.pid")"

nohup bash "${ROOT_DIR}/scripts/postscreen_mobile_pi05_training_rocm.sh" \
  "${train_pid}" "${TRAIN_LOG}" "${RUN_ROOT}" "${DATASET_ROOT}" \
  "${SCREEN_ROOT}" pi05-b1-droid-absolute-v2 3000 6000 9000 12000 \
  >"${POST_LOG}" 2>&1 </dev/null &
post_pid=$!
printf '%s\n' "${post_pid}" >"${POST_LOG}.pid"

nohup bash "${ROOT_DIR}/scripts/advance_mobile_pi05_b0_after_postscreen_rocm.sh" \
  "${post_pid}" "${RUN_ROOT}" "${SCREEN_ROOT}" "${STRICT_ROOT}" \
  pi05-b1-droid-absolute-v2 b1-v2 \
  >"${AUTO_LOG}" 2>&1 </dev/null &
auto_pid=$!
printf '%s\n' "${auto_pid}" >"${AUTO_LOG}.pid"

sleep 2
for pid in "${train_pid}" "${post_pid}" "${auto_pid}"; do
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "ERROR: B1 retry pipeline process exited during launch: ${pid}" >&2
    exit 2
  fi
done
printf '{"status":"started","training_pid":%s,"post_pid":%s,"auto_pid":%s}\n' \
  "${train_pid}" "${post_pid}" "${auto_pid}"
