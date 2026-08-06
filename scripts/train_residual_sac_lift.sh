#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python}"
POLICY_PATH="${POLICY_PATH:-${PROJECT_ROOT}/artifacts/models/smolvla_fruit_pick_dr_600ep}"
DATASET_ROOT="${DATASET_ROOT:-${PROJECT_ROOT}/artifacts/datasets/fruit_pick_dr_600ep}"
REPO_ID="${REPO_ID:-demo/fruit_pick_dr_600ep}"
OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_ROOT}/reproductions/rl/plum_residual_sac}"
TOTAL_STEPS="${TOTAL_STEPS:-100000}"
DRY_RUN="${DRY_RUN:-0}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "error: Python executable not found: ${PYTHON_BIN}" >&2
    exit 1
fi

cmd=(
    "${PYTHON_BIN}" -m franka_fruit_pick.residual_rl.train
    --policy-path "${POLICY_PATH}"
    --repo-id "${REPO_ID}"
    --dataset-root "${DATASET_ROOT}"
    --output-dir "${OUTPUT_DIR}"
    --total-steps "${TOTAL_STEPS}"
    --warmup-steps 10000
    --batch-size 256
    --replay-size 500000
    --updates-per-step 1
    --save-every 10000
    --seed 3000
    --seed-count 2000
    --device cuda
    --jitter 0.03
    --task-mode lift
    --arm-scale 0.015
    --finger-scale 0.003
    --warmup-range 0.25
    --gamma 0.99
    --tau 0.005
    --lr 0.0003
)

cd "${PROJECT_ROOT}"
if [[ "${DRY_RUN}" == "1" ]]; then
    printf 'Training command:'
    printf ' %q' "${cmd[@]}" "$@"
    printf '\n'
    exit 0
fi

if [[ ! -f "${DATASET_ROOT}/meta/info.json" ]]; then
    echo "error: LeRobot dataset not found: ${DATASET_ROOT}/meta/info.json" >&2
    exit 1
fi
if [[ ! -f "${POLICY_PATH}/model.safetensors" ]]; then
    echo "error: frozen SmolVLA checkpoint not found: ${POLICY_PATH}/model.safetensors" >&2
    exit 1
fi

# Genesis may install an exception hook that prints a traceback but leaves a
# successful process status. Check both the status and captured launcher log.
mkdir -p "$(dirname -- "${OUTPUT_DIR}")"
LAUNCH_LOG="${OUTPUT_DIR}.launcher.log"
set +e
"${cmd[@]}" "$@" 2>&1 | tee "${LAUNCH_LOG}"
status=${PIPESTATUS[0]}
set -e
if [[ ${status} -ne 0 ]] || grep -q '^Traceback (most recent call last):' "${LAUNCH_LOG}"; then
    echo "error: Residual SAC training failed; inspect ${LAUNCH_LOG}" >&2
    exit 1
fi
