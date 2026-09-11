#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:-${ROOT_DIR}/outputs/radeon-dataset/expert/lerobot_dataset}"
OUTPUT_ROOT="${2:-${ROOT_DIR}/outputs/benchmarks/act-training-$(date +%Y%m%d-%H%M%S)}"
STEPS="${ACT_BENCH_STEPS:-200}"
NUM_WORKERS="${ACT_BENCH_NUM_WORKERS:-4}"

if [[ -e "${OUTPUT_ROOT}" ]]; then
  echo "ERROR: benchmark output already exists: ${OUTPUT_ROOT}" >&2
  exit 2
fi
mkdir -p "${OUTPUT_ROOT}"

run_case() {
  local label="$1"
  local batch_size="$2"
  local use_amp="$3"
  local output_dir="${OUTPUT_ROOT}/${label}"
  local log_file="${OUTPUT_ROOT}/${label}.log"

  echo "Running ${label}: batch=${batch_size}, amp=${use_amp}, steps=${STEPS}"
  ACT_STEPS="${STEPS}" \
  ACT_BATCH_SIZE="${batch_size}" \
  ACT_NUM_WORKERS="${NUM_WORKERS}" \
  ACT_USE_AMP="${use_amp}" \
  ACT_EVAL_SPLIT=0 \
  ACT_EVAL_STEPS=0 \
  ACT_LOG_FREQ="${STEPS}" \
  ACT_SAVE_CHECKPOINT=false \
    bash "${ROOT_DIR}/scripts/train_act_rocm.sh" \
      "${DATASET_ROOT}" \
      "${output_dir}" >"${log_file}" 2>&1

  grep -a "step:${STEPS}" "${log_file}" | tail -1 || true
}

run_case fp32-b8 8 false
run_case fp32-b32 32 false
run_case amp-b32 32 true

echo "ACT training benchmark logs: ${OUTPUT_ROOT}"
