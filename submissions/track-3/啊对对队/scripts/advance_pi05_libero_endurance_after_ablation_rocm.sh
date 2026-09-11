#!/usr/bin/env bash
# Run the fixed-state 120-attempt endurance protocol after runtime selection.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ABLATION_PID="${1:?usage: $0 ABLATION_PID}"
CHECKPOINT="/root/pi05-assets/pi05-libero-finetuned-local"
MANIFEST="${ROOT_DIR}/configs/pi05_libero_public_benchmark_v2.json"
CONFIG="${ROOT_DIR}/configs/pi05_libero_radeon_endurance_v1.json"
ABLATION_SUMMARY="${ROOT_DIR}/outputs/pi05-libero-radeon-compile-ablation-v1/ABLATION_SUMMARY.json"
OUTPUT_ROOT="${ROOT_DIR}/outputs/pi05-libero-radeon-endurance-v1"
SELECTION="${OUTPUT_ROOT}/RUNTIME_SELECTION.json"
SUMMARY="${OUTPUT_ROOT}/ENDURANCE_SUMMARY.json"
STATUS="${OUTPUT_ROOT}/STATUS.json"

if [[ ! "${ABLATION_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: ABLATION_PID must be a positive integer" >&2
  exit 2
fi
if [[ -e "${OUTPUT_ROOT}" ]]; then
  echo "ERROR: endurance output already exists: ${OUTPUT_ROOT}" >&2
  exit 3
fi

while kill -0 "${ABLATION_PID}" 2>/dev/null; do
  sleep 60
done

if [[ ! -f "${ABLATION_SUMMARY}" ]]; then
  echo "ERROR: Radeon compile ablation did not complete" >&2
  exit 4
fi

export PYTHONPATH="/workspace/libero-overlay:/workspace/parcel-sorter-rocm/third_party/lerobot/src:${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export MUJOCO_GL=egl
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export WANDB_DISABLED=true

mkdir -p "${OUTPUT_ROOT}"
compile_override="$(/workspace/rdna/bin/python "${ROOT_DIR}/scripts/select_pi05_libero_radeon_runtime.py" \
  --ablation-summary "${ABLATION_SUMMARY}" --output "${SELECTION}")"

timeout 172800s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/run_pi05_libero_eval_rocm.py" \
  --checkpoint "${CHECKPOINT}" --manifest "${MANIFEST}" --output "${OUTPUT_ROOT}" \
  --phase endurance --compile "${compile_override}"

/workspace/rdna/bin/python "${ROOT_DIR}/scripts/summarize_pi05_libero_radeon_endurance.py" \
  --config "${CONFIG}" --run-root "${OUTPUT_ROOT}" --output "${SUMMARY}"

printf '{"schema_version":1,"status":"complete","config":"%s","summary":"%s"}\n' \
  "${CONFIG}" "${SUMMARY}" >"${STATUS}"
cat "${STATUS}"
