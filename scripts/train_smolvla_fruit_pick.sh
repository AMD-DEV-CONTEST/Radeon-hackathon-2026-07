#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python}"
DATASET_ROOT="${DATASET_ROOT:-${PROJECT_ROOT}/artifacts/datasets/fruit_pick_dr_600ep}"
REPO_ID="${REPO_ID:-demo/fruit_pick_dr_600ep}"
POLICY_PATH="${POLICY_PATH:-lerobot/smolvla_base}"
OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_ROOT}/reproductions/train/smolvla_fruit_pick_dr_600ep}"
RUN_NAME="${RUN_NAME:-smolvla_fruit_pick_dr_600ep}"
STEPS="${STEPS:-20000}"
BATCH_SIZE="${BATCH_SIZE:-128}"
SAVE_FREQ="${SAVE_FREQ:-2000}"
DRY_RUN="${DRY_RUN:-0}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "error: Python executable not found: ${PYTHON_BIN}" >&2
    exit 1
fi

if [[ "${DRY_RUN}" != "1" && ! -f "${DATASET_ROOT}/meta/info.json" ]]; then
    echo "error: LeRobot dataset not found: ${DATASET_ROOT}/meta/info.json" >&2
    echo "download it according to artifacts/README.md or set DATASET_ROOT" >&2
    exit 1
fi

cmd=(
    "${PYTHON_BIN}" "${PROJECT_ROOT}/franka_fruit_pick/train_policy.py" smolvla
    --policy-path "${POLICY_PATH}"
    --repo-id "${REPO_ID}"
    --dataset-root "${DATASET_ROOT}"
    --output-dir "${OUTPUT_DIR}"
    --name "${RUN_NAME}"
    --steps "${STEPS}"
    --batch-size "${BATCH_SIZE}"
    --save-freq "${SAVE_FREQ}"
    --device cuda
)

if [[ "${DRY_RUN}" == "1" ]]; then
    cmd+=(--dry-run)
fi

cd "${PROJECT_ROOT}"
if [[ "${DRY_RUN}" == "1" ]]; then
    exec "${cmd[@]}" "$@"
fi

# LeRobot 0.6.0 may print an uncaught traceback yet return status 0. Preserve the
# complete launcher log and treat either a non-zero status or traceback as failure.
mkdir -p "$(dirname -- "${OUTPUT_DIR}")"
LAUNCH_LOG="${OUTPUT_DIR}.launcher.log"
set +e
"${cmd[@]}" "$@" 2>&1 | tee "${LAUNCH_LOG}"
status=${PIPESTATUS[0]}
set -e
if [[ ${status} -ne 0 ]] || grep -q '^Traceback (most recent call last):' "${LAUNCH_LOG}"; then
    echo "error: SmolVLA training failed; inspect ${LAUNCH_LOG}" >&2
    exit 1
fi
