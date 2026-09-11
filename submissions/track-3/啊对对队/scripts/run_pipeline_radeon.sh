#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-${ROOT_DIR}/outputs/radeon-run}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh

python scripts/smoke_rocm.py
python scripts/run_expert.py \
  --backend rocm \
  --episodes 3 \
  --record-video \
  --output "${OUTPUT_DIR}"
python scripts/evaluate_robustness.py \
  --backend rocm \
  --episodes-per-profile 3 \
  --output "${OUTPUT_DIR}"
python scripts/benchmark_parallel.py \
  --backend rocm \
  --env-counts 1,16,64,128 \
  --output "${OUTPUT_DIR}/benchmarks/parallel.json"
python scripts/generate_report.py \
  --input "${OUTPUT_DIR}" \
  --output "${OUTPUT_DIR}/technical_report_draft.md"

echo "Radeon pipeline completed: ${OUTPUT_DIR}"
