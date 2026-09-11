#!/usr/bin/env bash
# Train and screen the stage-complete PI0.5 tiny-overfit contract.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USAGE="usage: $0 TINY_DATASET_ROOT STAGE_PANEL ACTION_THRESHOLDS RUN_ROOT EVIDENCE_DIR"
DATASET_ROOT="${1:?${USAGE}}"
STAGE_PANEL="${2:?${USAGE}}"
ACTION_THRESHOLDS="${3:?${USAGE}}"
RUN_ROOT="${4:?${USAGE}}"
EVIDENCE_DIR="${5:?${USAGE}}"
STEPS="${MOBILE_PI05_STEPS:-1500}"

if pgrep -f "lerobot_train|train_mobile_pi05_rocm.sh" >/dev/null; then
  echo "ERROR: another PI0.5 training process is active" >&2
  exit 2
fi
for path in "${DATASET_ROOT}" "${STAGE_PANEL}" "${ACTION_THRESHOLDS}"; do
  test -e "${path}" || { echo "ERROR: missing tiny-overfit input: ${path}" >&2; exit 2; }
done

export MOBILE_PI05_TRAINING_ROLE=tiny_overfit
export MOBILE_PI05_ACTION_CONTRACT=absolute_v1
export MOBILE_PI05_FULL_ACTION_PROJECTIONS=1
export MOBILE_PI05_TINY_OVERFIT_PANEL="${STAGE_PANEL}"
export MOBILE_PI05_ACTION_THRESHOLDS="${ACTION_THRESHOLDS}"
export MOBILE_PI05_STEPS="${STEPS}"
export MOBILE_PI05_SAVE_FREQ="${STEPS}"
export MOBILE_PI05_SCHEDULER_WARMUP_STEPS="${MOBILE_PI05_SCHEDULER_WARMUP_STEPS:-50}"
export MOBILE_PI05_SCHEDULER_DECAY_STEPS="${STEPS}"

bash "${ROOT_DIR}/scripts/train_mobile_pi05_rocm.sh" "${DATASET_ROOT}" "${RUN_ROOT}"
bash "${ROOT_DIR}/scripts/screen_mobile_pi05_checkpoints_rocm.sh" \
  "${RUN_ROOT}" "${DATASET_ROOT}" "${STAGE_PANEL}" "${ACTION_THRESHOLDS}" \
  "${EVIDENCE_DIR}" tiny-overfit "${STEPS}"

printf -v checkpoint_step "%06d" "${STEPS}"
checkpoint="${RUN_ROOT}/checkpoints/${checkpoint_step}/pretrained_model"
screen="${EVIDENCE_DIR}/tiny-overfit-step${STEPS}-stage-panel-screen.json"
python "${ROOT_DIR}/scripts/write_mobile_pi05_tiny_overfit_gate.py" \
  --screen "${screen}" \
  --panel "${STAGE_PANEL}" \
  --thresholds "${ACTION_THRESHOLDS}" \
  --checkpoint "${checkpoint}" \
  --training-contract "${RUN_ROOT}/PI05_TRAINING_CONTRACT.json" \
  --output "${EVIDENCE_DIR}/PI05_TINY_OVERFIT_GATE.json"
