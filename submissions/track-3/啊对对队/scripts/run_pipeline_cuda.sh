#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-${ROOT_DIR}/outputs/cuda-run}"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${ROOT_DIR}"
bash scripts/preflight_cuda.sh
source .venv-cuda/bin/activate

python scripts/run_expert.py \
  --backend cuda \
  --episodes 3 \
  --record-video \
  --output "${OUTPUT_DIR}"
python scripts/evaluate_robustness.py \
  --backend cuda \
  --episodes-per-profile 3 \
  --output "${OUTPUT_DIR}"
python scripts/benchmark_parallel.py \
  --backend cuda \
  --env-counts 1,16,64,128 \
  --output "${OUTPUT_DIR}/benchmarks/parallel.json"
python scripts/generate_report.py \
  --input "${OUTPUT_DIR}" \
  --output "${OUTPUT_DIR}/technical_report_draft.md"

echo "CUDA development pipeline completed: ${OUTPUT_DIR}"
