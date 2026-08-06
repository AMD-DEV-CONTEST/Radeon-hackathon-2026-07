#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
POLICY_PATH="${POLICY_PATH:-${PROJECT_ROOT}/artifacts/models/smolvla_fruit_pick_dr_600ep}"
DATASET_ROOT="${DATASET_ROOT:-${PROJECT_ROOT}/artifacts/datasets/fruit_pick_dr_600ep}"
REPO_ID="${REPO_ID:-demo/fruit_pick_dr_600ep}"
OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_ROOT}/reproductions/runtime}"
CAPTURE_WARMUP="${CAPTURE_WARMUP:-3}"
COMPILE_MODE="${COMPILE_MODE:-max-autotune-no-cudagraphs}"
MATMUL_PRECISION="${MATMUL_PRECISION:-highest}"
ATOL="${ATOL:-1e-4}"
RTOL="${RTOL:-1e-3}"
BACKENDS="${BACKENDS:-hip-graph compile}"
DRY_RUN="${DRY_RUN:-0}"

command -v "${PYTHON_BIN}" >/dev/null 2>&1 || { echo "error: Python not found: ${PYTHON_BIN}" >&2; exit 1; }
if [[ "${DRY_RUN}" != "1" ]]; then
    test -f "${POLICY_PATH}/model.safetensors" || { echo "error: policy not found: ${POLICY_PATH}" >&2; exit 1; }
    test -f "${DATASET_ROOT}/meta/info.json" || { echo "error: dataset not found: ${DATASET_ROOT}" >&2; exit 1; }
fi

mkdir -p "${OUTPUT_DIR}"
cd "${PROJECT_ROOT}"
for backend in ${BACKENDS}; do
    case "${backend}" in hip-graph|compile) ;; *) echo "error: validation backend must be hip-graph or compile" >&2; exit 2;; esac
    cmd=("${PYTHON_BIN}" -m optimization.runtime.validate_full_inference
        --backend "${backend}" --policy-path "${POLICY_PATH}" --repo-id "${REPO_ID}"
        --dataset-root "${DATASET_ROOT}" --device cuda --capture-warmup "${CAPTURE_WARMUP}"
        --compile-mode "${COMPILE_MODE}" --matmul-precision "${MATMUL_PRECISION}"
        --atol "${ATOL}" --rtol "${RTOL}" --output "${OUTPUT_DIR}/validation_${backend}.json")
    if [[ "${DRY_RUN}" == "1" ]]; then printf 'Validation command:'; printf ' %q' "${cmd[@]}"; printf '\n'; continue; fi
    log="${OUTPUT_DIR}/validation_${backend}.log"
    set +e; "${cmd[@]}" 2>&1 | tee "${log}"; status=${PIPESTATUS[0]}; set -e
    if [[ ${status} -ne 0 ]] || grep -q '^Traceback (most recent call last):' "${log}"; then
        echo "error: ${backend} validation failed to execute; inspect ${log}" >&2; exit 1
    fi
done
if [[ "${DRY_RUN}" != "1" && -f "${OUTPUT_DIR}/full_eager.json" ]]; then
    "${PYTHON_BIN}" -m optimization.runtime.summarize_results --results-dir "${OUTPUT_DIR}"
fi
