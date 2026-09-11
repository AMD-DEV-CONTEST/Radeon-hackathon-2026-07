#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WAIT_PID="${1:?usage: watch_then_train_smolvla_smoke_rocm.sh WAIT_PID}"
DATASET_ROOT="${ROOT_DIR}/outputs/radeon-dataset-400-v2/expert/lerobot_dataset"
SPLIT_MANIFEST="${ROOT_DIR}/outputs/radeon-dataset-400-v2/dataset-split.json"
OUTPUT_DIR="${ROOT_DIR}/outputs/train/smolvla-strict-open-smoke-seed11"

while kill -0 "${WAIT_PID}" 2>/dev/null; do
  sleep 30
done

cd "${ROOT_DIR}"
export SMOLVLA_STEPS=20
export SMOLVLA_BATCH_SIZE=1
export SMOLVLA_NUM_WORKERS=2
export SMOLVLA_SAVE_FREQ=20
export SMOLVLA_EVAL_STEPS=0
export SMOLVLA_SEED=11

bash scripts/train_smolvla_rocm.sh \
  "${DATASET_ROOT}" \
  "${OUTPUT_DIR}" \
  "${SPLIT_MANIFEST}"
