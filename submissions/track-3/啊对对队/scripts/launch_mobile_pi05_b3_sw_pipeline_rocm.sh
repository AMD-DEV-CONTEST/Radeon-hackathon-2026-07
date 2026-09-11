#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PERSISTENCE_ROOT="${PI05_PERSISTENCE_ROOT:-/workspace/persistence/parcel-sorter-opt-v1}"
RUN_VERSION="${1:-v1}"
[[ "${RUN_VERSION}" =~ ^v[1-9][0-9]*$ ]] || {
  echo "ERROR: run version must match vN, got: ${RUN_VERSION}" >&2
  exit 2
}

DATASET_ROOT="${ROOT_DIR}/outputs/pi05-b0-absolute-v1-merged"
RUN_ROOT="${PERSISTENCE_ROOT}/runs/mobile-pi05-b3-sw-stage-weighted-12000-${RUN_VERSION}"
TRAIN_LOG="${PERSISTENCE_ROOT}/outputs/pi05-b3-sw-stage-weighted-train-${RUN_VERSION}.log"
SCREEN_ROOT="${PERSISTENCE_ROOT}/outputs/pi05-b3-sw-stage-weighted-common-seed-${RUN_VERSION}"
POST_LOG="${PERSISTENCE_ROOT}/outputs/pi05-b3-sw-stage-weighted-postscreen-${RUN_VERSION}.log"
ADVANCE_LOG="${PERSISTENCE_ROOT}/outputs/pi05-b3-sw-stage-weighted-advance-${RUN_VERSION}.log"
STRICT_ROOT="${PERSISTENCE_ROOT}/outputs/pi05-b3-sw-stage-weighted-strict-dev-${RUN_VERSION}"
ARTIFACT_ROOT="${PERSISTENCE_ROOT}/artifacts/mobile-pi05-b3-sw-stage-weighted-${RUN_VERSION}"
PREREG_CONFIG="${ROOT_DIR}/configs/mobile_pi05_b3_sw_stage_weighted_flow_v1.json"
STAGE_WEIGHTS="2.035714286,2.035714286,1.221428571,0.407142857,0.610714286,0.407142857"

if [[ -e "${ARTIFACT_ROOT}" || -e "${POST_LOG}" || -e "${ADVANCE_LOG}" || -e "${STRICT_ROOT}" ]]; then
  echo "ERROR: B3-SW artifact, post-screen, advance, or strict output already exists" >&2
  exit 2
fi
mkdir -p "${ARTIFACT_ROOT}"
install -m 0444 "${PREREG_CONFIG}" "${ARTIFACT_ROOT}/PRE_REGISTERED_CONFIG.json"
sha256sum \
  "${PREREG_CONFIG}" \
  "${ROOT_DIR}/scripts/launch_mobile_pi05_b3_sw_pipeline_rocm.sh" \
  "${ROOT_DIR}/scripts/launch_mobile_pi05_b3_sw_stage_weighted_rocm.sh" \
  "${ROOT_DIR}/scripts/train_mobile_pi05_rocm.sh" \
  "${ROOT_DIR}/scripts/screen_mobile_pi05_checkpoints_rocm.sh" \
  "${ROOT_DIR}/scripts/advance_mobile_pi05_b3_sw_after_postscreen_rocm.sh" \
  "${ROOT_DIR}/scripts/compare_mobile_pi05_action_fidelity.py" \
  "${ROOT_DIR}/src/parcel_sorter/pi05_weighted_loss.py" \
  "${ROOT_DIR}/src/parcel_sorter/mobile_pi05_training_contract.py" \
  >"${ARTIFACT_ROOT}/SOURCE_SHA256SUMS.txt"

bash "${ROOT_DIR}/scripts/launch_mobile_pi05_b3_sw_stage_weighted_rocm.sh" \
  "${DATASET_ROOT}" "${RUN_ROOT}" "${TRAIN_LOG}"
train_pid="$(tr -d '[:space:]' <"${TRAIN_LOG}.pid")"

nohup env \
  MOBILE_PI05_REQUIRE_ACTION_FIDELITY=1 \
  MOBILE_PI05_REQUIRE_FULL_ACTION_PROJECTIONS=1 \
  MOBILE_PI05_EXPECTED_STAGE_LOSS_WEIGHTS="${STAGE_WEIGHTS}" \
  bash "${ROOT_DIR}/scripts/postscreen_mobile_pi05_training_rocm.sh" \
  "${train_pid}" "${TRAIN_LOG}" "${RUN_ROOT}" "${DATASET_ROOT}" \
  "${SCREEN_ROOT}" pi05-b3-sw-stage-weighted 3000 6000 9000 12000 \
  >"${POST_LOG}" 2>&1 </dev/null &
post_pid=$!
printf '%s\n' "${post_pid}" >"${POST_LOG}.pid"

nohup bash "${ROOT_DIR}/scripts/advance_mobile_pi05_b3_sw_after_postscreen_rocm.sh" \
  "${post_pid}" "${SCREEN_ROOT}" "${STRICT_ROOT}" \
  pi05-b3-sw-stage-weighted b3-sw \
  >"${ADVANCE_LOG}" 2>&1 </dev/null &
advance_pid=$!
printf '%s\n' "${advance_pid}" >"${ADVANCE_LOG}.pid"

sleep 2
for pid in "${train_pid}" "${post_pid}" "${advance_pid}"; do
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "ERROR: B3-SW pipeline process exited during launch: ${pid}" >&2
    exit 3
  fi
done
printf '{"status":"started","candidate":"B3-SW","training_pid":%s,"post_pid":%s,"advance_pid":%s,"run_root":"%s","screen_root":"%s","strict_root":"%s","artifact_root":"%s","automatic_confirmation":false}\n' \
  "${train_pid}" "${post_pid}" "${advance_pid}" "${RUN_ROOT}" "${SCREEN_ROOT}" \
  "${STRICT_ROOT}" "${ARTIFACT_ROOT}"
