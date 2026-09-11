#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)
if [ "$#" -ne 1 ]; then
  echo "usage: watch_and_train_rocm.sh RUN_ROOT" >&2
  exit 64
fi
RUN_ROOT=$1
DATASET_ROOT=$RUN_ROOT/expert/lerobot_dataset
AUDIT_ROOT=$RUN_ROOT/expert/audit_dataset
SPLIT_MANIFEST=$RUN_ROOT/dataset-split.json
POLL_SECONDS="${WATCH_POLL_SECONDS:-30}"
MODEL_SWEEP_MODELS="${MODEL_SWEEP_MODELS:-act}"
MODEL_SWEEP_SEEDS="${MODEL_SWEEP_SEEDS:-11,22,33}"
MODEL_SWEEP_ACT_STEPS="${MODEL_SWEEP_ACT_STEPS:-30000}"
MODEL_SWEEP_OUTPUT_ROOT="${MODEL_SWEEP_OUTPUT_ROOT:-$RUN_ROOT/model-sweep}"

export HIP_VISIBLE_DEVICES=0
export PYTHONPATH=$ROOT_DIR/src
cd "$ROOT_DIR"
source scripts/activate_radeon_env.sh

echo "waiting for completed collection: $RUN_ROOT/expert/summary.json"
while [ ! -f "$RUN_ROOT/expert/summary.json" ]; do
  sleep "$POLL_SECONDS"
done

python scripts/build_dataset_split.py \
  --audit-root "$AUDIT_ROOT" \
  --dataset-root "$DATASET_ROOT" \
  --output "$SPLIT_MANIFEST" \
  --seed 20260725

MODEL_SWEEP_MODELS=$MODEL_SWEEP_MODELS \
MODEL_SWEEP_SEEDS=$MODEL_SWEEP_SEEDS \
MODEL_SWEEP_ACT_STEPS=$MODEL_SWEEP_ACT_STEPS \
bash scripts/run_model_sweep_rocm.sh \
  "$DATASET_ROOT" \
  "$SPLIT_MANIFEST" \
  "$MODEL_SWEEP_OUTPUT_ROOT"
