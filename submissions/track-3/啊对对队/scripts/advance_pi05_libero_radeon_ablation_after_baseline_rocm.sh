#!/usr/bin/env bash
# Run a drift-balanced compile ablation only after the official PI0.5 baseline completes.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE_PID="${1:?usage: $0 BASELINE_PID}"
CHECKPOINT="/root/pi05-assets/pi05-libero-finetuned-local"
MANIFEST="${ROOT_DIR}/configs/pi05_libero_public_benchmark_v2.json"
CONFIG="${ROOT_DIR}/configs/pi05_libero_radeon_compile_ablation_v1.json"
BASELINE_STATUS="${ROOT_DIR}/outputs/pi05-libero-baseline-after-b2-status-v2.json"
OUTPUT_ROOT="${ROOT_DIR}/outputs/pi05-libero-radeon-compile-ablation-v1"
SUMMARY="${OUTPUT_ROOT}/ABLATION_SUMMARY.json"
STATUS="${OUTPUT_ROOT}/STATUS.json"

if [[ ! "${BASELINE_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: BASELINE_PID must be a positive integer" >&2
  exit 2
fi
if [[ -e "${OUTPUT_ROOT}" ]]; then
  echo "ERROR: Radeon ablation output already exists: ${OUTPUT_ROOT}" >&2
  exit 3
fi

while kill -0 "${BASELINE_PID}" 2>/dev/null; do
  sleep 60
done

if [[ ! -f "${BASELINE_STATUS}" ]]; then
  echo "ERROR: official PI0.5 baseline did not complete" >&2
  exit 4
fi

export PYTHONPATH="/workspace/libero-overlay:/workspace/parcel-sorter-rocm/third_party/lerobot/src:${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export MUJOCO_GL=egl
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export WANDB_DISABLED=true

mkdir -p "${OUTPUT_ROOT}"

timeout 86400s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/run_pi05_libero_eval_rocm.py" \
  --checkpoint "${CHECKPOINT}" --manifest "${MANIFEST}" \
  --output "${OUTPUT_ROOT}/compile_false_r1" --phase efficiency --compile false

timeout 86400s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/run_pi05_libero_eval_rocm.py" \
  --checkpoint "${CHECKPOINT}" --manifest "${MANIFEST}" \
  --output "${OUTPUT_ROOT}/compile_true_r1" --phase efficiency --compile true

timeout 86400s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/run_pi05_libero_eval_rocm.py" \
  --checkpoint "${CHECKPOINT}" --manifest "${MANIFEST}" \
  --output "${OUTPUT_ROOT}/compile_true_r2" --phase efficiency --compile true

timeout 86400s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/run_pi05_libero_eval_rocm.py" \
  --checkpoint "${CHECKPOINT}" --manifest "${MANIFEST}" \
  --output "${OUTPUT_ROOT}/compile_false_r2" --phase efficiency --compile false

/workspace/rdna/bin/python "${ROOT_DIR}/scripts/summarize_pi05_libero_radeon_compile_ablation.py" \
  --config "${CONFIG}" --run-root "${OUTPUT_ROOT}" --output "${SUMMARY}"

printf '{"schema_version":1,"status":"complete","config":"%s","summary":"%s"}\n' \
  "${CONFIG}" "${SUMMARY}" >"${STATUS}"
cat "${STATUS}"
