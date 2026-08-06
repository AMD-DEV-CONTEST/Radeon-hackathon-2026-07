#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
POLICY_PATH="${POLICY_PATH:-${PROJECT_ROOT}/artifacts/models/smolvla_fruit_pick_dr_600ep}"
DATASET_ROOT="${DATASET_ROOT:-${PROJECT_ROOT}/artifacts/datasets/fruit_pick_dr_600ep}"
REPO_ID="${REPO_ID:-demo/fruit_pick_dr_600ep}"
CANDIDATE="${CANDIDATE:-hip-graph}"
EPISODES="${EPISODES:-100}"
SEED="${SEED:-2000}"
POLICY_SEED="${POLICY_SEED:-2000}"
JITTER="${JITTER:-0.03}"
CAPTURE_WARMUP="${CAPTURE_WARMUP:-3}"
COMPILE_MODE="${COMPILE_MODE:-max-autotune-no-cudagraphs}"
MATMUL_PRECISION="${MATMUL_PRECISION:-highest}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${PROJECT_ROOT}/reproductions/closed_loop/${CANDIDATE}}"
FRUITS="${FRUITS:-banana lemon plum}"
DRY_RUN="${DRY_RUN:-0}"

case "${CANDIDATE}" in hip-graph|targeted-compile) ;; *) echo "error: CANDIDATE must be hip-graph or targeted-compile" >&2; exit 2;; esac
[[ "${EPISODES}" =~ ^[1-9][0-9]*$ ]] || { echo "error: EPISODES must be positive" >&2; exit 2; }
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || { echo "error: Python not found: ${PYTHON_BIN}" >&2; exit 1; }
if [[ "${DRY_RUN}" != "1" ]]; then
    test -f "${POLICY_PATH}/model.safetensors" || { echo "error: policy not found: ${POLICY_PATH}" >&2; exit 1; }
    test -f "${DATASET_ROOT}/meta/info.json" || { echo "error: dataset not found: ${DATASET_ROOT}" >&2; exit 1; }
fi

export HSA_ENABLE_SDMA="${HSA_ENABLE_SDMA:-0}"
unset PYOPENGL_PLATFORM || true
candidate_dir="${CANDIDATE//-/_}"
mkdir -p "${OUTPUT_ROOT}/eager" "${OUTPUT_ROOT}/${candidate_dir}"
cd "${PROJECT_ROOT}"
for backend in eager "${CANDIDATE}"; do
    output_backend="${backend//-/_}"
    while read -r fruit object_id; do
        case " ${FRUITS} " in *" ${fruit} "*) ;; *) continue;; esac
        cmd=("${PYTHON_BIN}" franka_fruit_pick/eval_policy.py --policy-path "${POLICY_PATH}"
            --repo-id "${REPO_ID}" --dataset-root "${DATASET_ROOT}" --episodes "${EPISODES}"
            --seed "${SEED}" --policy-seed "${POLICY_SEED}" --pick "${object_id}"
            --jitter "${JITTER}" --device cuda --inference-backend "${backend}"
            --hip-graph-capture-warmup "${CAPTURE_WARMUP}" --compile-mode "${COMPILE_MODE}"
            --matmul-precision "${MATMUL_PRECISION}" --measure-inference
            --results-out "${OUTPUT_ROOT}/${output_backend}/${fruit}_${EPISODES}ep.json")
        if command -v xvfb-run >/dev/null 2>&1; then cmd=(xvfb-run -a -s '-screen 0 1280x720x24' "${cmd[@]}"); fi
        if [[ "${DRY_RUN}" == "1" ]]; then printf 'Closed-loop command:'; printf ' %q' "${cmd[@]}"; printf '\n'; continue; fi
        log="${OUTPUT_ROOT}/${output_backend}/${fruit}_${EPISODES}ep.log"
        set +e; "${cmd[@]}" 2>&1 | tee "${log}"; status=${PIPESTATUS[0]}; set -e
        if [[ ${status} -ne 0 ]] || grep -q '^Traceback (most recent call last):' "${log}"; then
            echo "error: closed-loop run failed; inspect ${log}" >&2; exit 1
        fi
    done <<'EOF'
banana 011_banana
lemon 014_lemon
plum 018_plum
EOF
done

if [[ "${DRY_RUN}" != "1" ]]; then
    if [[ " ${FRUITS} " != *' banana '* || " ${FRUITS} " != *' lemon '* || " ${FRUITS} " != *' plum '* ]]; then
        echo "[closed-loop] subset completed (${FRUITS}); skip three-fruit summary"
        exit 0
    fi
    summary=("${PYTHON_BIN}" -m optimization.runtime.summarize_closed_loop_ab "${OUTPUT_ROOT}"
        --episodes "${EPISODES}" --csv-out "${OUTPUT_ROOT}/summary_${EPISODES}ep.csv"
        --markdown-out "${OUTPUT_ROOT}/summary_${EPISODES}ep.md")
    if [[ "${CANDIDATE}" == "targeted-compile" ]]; then summary+=(--candidate targeted_compile --candidate-label 'Targeted compile'); fi
    "${summary[@]}"
fi
