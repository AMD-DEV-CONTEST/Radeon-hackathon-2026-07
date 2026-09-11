#!/usr/bin/env bash
# Wait for one PI0.5 training run, then evaluate all requested checkpoints.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_PANEL="${MOBILE_PI05_STAGE_PANEL:?postscreen requires MOBILE_PI05_STAGE_PANEL}"
ACTION_THRESHOLDS="${MOBILE_PI05_ACTION_THRESHOLDS:?postscreen requires MOBILE_PI05_ACTION_THRESHOLDS}"
TRAIN_PID="${1:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT DATASET_ROOT OUTPUT_DIR RUN_NAME [STEP ...]}"
TRAIN_LOG="${2:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT DATASET_ROOT OUTPUT_DIR RUN_NAME [STEP ...]}"
RUN_ROOT="${3:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT DATASET_ROOT OUTPUT_DIR RUN_NAME [STEP ...]}"
DATASET_ROOT="${4:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT DATASET_ROOT OUTPUT_DIR RUN_NAME [STEP ...]}"
OUTPUT_DIR="${5:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT DATASET_ROOT OUTPUT_DIR RUN_NAME [STEP ...]}"
RUN_NAME="${6:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT DATASET_ROOT OUTPUT_DIR RUN_NAME [STEP ...]}"
shift 6
if [[ "$#" -eq 0 ]]; then
  STEPS=(3000 6000 9000 12000)
else
  STEPS=("$@")
fi

if [[ ! "${TRAIN_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: TRAIN_PID must be a positive integer" >&2
  exit 2
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
  echo "ERROR: post-screen output already exists: ${OUTPUT_DIR}" >&2
  exit 3
fi

while kill -0 "${TRAIN_PID}" 2>/dev/null; do
  sleep 60
done

if [[ ! -f "${TRAIN_LOG}" ]] || ! grep -q "End of training" "${TRAIN_LOG}"; then
  echo "ERROR: training process ended without an audited completion marker" >&2
  exit 4
fi

mkdir -p "${OUTPUT_DIR}"
screen_status=0
bash "${ROOT_DIR}/scripts/screen_mobile_pi05_checkpoints_rocm.sh" \
  "${RUN_ROOT}" "${DATASET_ROOT}" "${STAGE_PANEL}" "${ACTION_THRESHOLDS}" \
  "${OUTPUT_DIR}" "${RUN_NAME}" \
  "${STEPS[@]}" || screen_status=$?

if [[ "${screen_status}" -ge 3 ]]; then
  echo "ERROR: structural checkpoint screen failure; skipping GPU diagnostics" >&2
  exit "${screen_status}"
fi
if [[ "${screen_status}" -eq 2 ]]; then
  echo "INFO: one or more checkpoints missed the scientific screen gate; continuing frozen diagnostics for later-checkpoint selection" >&2
elif [[ "${screen_status}" -ne 0 ]]; then
  echo "ERROR: unexpected checkpoint screen status: ${screen_status}" >&2
  exit "${screen_status}"
fi

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export TOKENIZERS_PARALLELISM=false
cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh

for step in "${STEPS[@]}"; do
  printf -v checkpoint_step "%06d" "${step}"
  checkpoint="${RUN_ROOT}/checkpoints/${checkpoint_step}/pretrained_model"
  output="${OUTPUT_DIR}/${RUN_NAME}-step${step}-high-noise-mode-probes.json"
  log="${OUTPUT_DIR}/${RUN_NAME}-step${step}-high-noise-mode-probes.log"
  python scripts/probe_mobile_pi05_high_noise_mode_rocm.py \
    "${checkpoint}" \
    "${DATASET_ROOT}" \
    --panel "${STAGE_PANEL}" \
    --samples 3 \
    --seed 20260727 \
    --output "${output}" 2>&1 | tee "${log}"
done

exit 0
