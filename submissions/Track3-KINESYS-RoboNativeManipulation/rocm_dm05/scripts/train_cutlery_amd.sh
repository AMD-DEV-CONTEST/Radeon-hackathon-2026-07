#!/usr/bin/env bash
set -euo pipefail

: "${OPENDM_ROOT:?Set OPENDM_ROOT to the patched OpenDM checkout}"
: "${PYTHON:?Set PYTHON to the ROCm environment Python executable}"
: "${TRAIN_DATASET:?Set TRAIN_DATASET to the 32-episode LeRobot v3 dataset}"
: "${BASE_MODEL:?Set BASE_MODEL to Dexmal/DM05 or a local base checkpoint}"
: "${OUTPUT_ROOT:?Set OUTPUT_ROOT}"

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
AMD_GPU_IDS=${AMD_GPU_IDS:-0}
NPROC=${NPROC:-1}
PER_DEVICE_BATCH=${PER_DEVICE_BATCH:-12}
GRADIENT_ACCUMULATION=${GRADIENT_ACCUMULATION:-4}
MAX_STEPS=${MAX_STEPS:-10000}
SAVE_STEPS=${SAVE_STEPS:-1000}
MODEL_MAX_LENGTH=${MODEL_MAX_LENGTH:-896}
DATALOADER_NUM_WORKERS=${DATALOADER_NUM_WORKERS:-2}
MASTER_PORT=${MASTER_PORT:-29981}
RUN_NAME=${RUN_NAME:-dm05-cutlery-long-amd}
OUTPUT_DIR="$OUTPUT_ROOT/$RUN_NAME"
NORM_ROOT="$OUTPUT_ROOT/norm-stats"
DATASET_NAME=${DATASET_NAME:-bigym_dishwasher_unload_cutlery_long_native20}

test -s "$TRAIN_DATASET/meta/info.json" || {
  echo "Incomplete LeRobot dataset: $TRAIN_DATASET" >&2
  exit 2
}
if [[ "$BASE_MODEL" == /* || "$BASE_MODEL" == ./* ]]; then
  test -d "$BASE_MODEL" || {
    echo "Base model directory does not exist: $BASE_MODEL" >&2
    exit 2
  }
fi
if [[ -e "$OUTPUT_DIR" ]] && ! compgen -G "$OUTPUT_DIR/checkpoint-*" >/dev/null; then
  echo "Refusing to reuse a non-checkpoint output directory: $OUTPUT_DIR" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR" "$NORM_ROOT"
export HIP_VISIBLE_DEVICES="$AMD_GPU_IDS"
export ROCR_VISIBLE_DEVICES="$AMD_GPU_IDS"
export PYTORCH_ROCM_ARCH=${PYTORCH_ROCM_ARCH:-gfx1100}
export TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1
export PYTORCH_ALLOC_CONF=${PYTORCH_ALLOC_CONF:-expandable_segments:True}
export PYTHONPATH="$OPENDM_ROOT:$PROJECT_ROOT/train${PYTHONPATH:+:$PYTHONPATH}"
export TOKENIZERS_PARALLELISM=false
export TORCH_NCCL_ASYNC_ERROR_HANDLING=1
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
export OPENDM_TUNABLEOP_TUNING=${OPENDM_TUNABLEOP_TUNING:-0}

trainer_args=(
  --trainer-config.model-max-length "$MODEL_MAX_LENGTH"
)
if [[ -n "${TUNABLEOP_FILENAME:-}" ]]; then
  test -s "$TUNABLEOP_FILENAME" || {
    echo "TunableOp replay database is missing or empty: $TUNABLEOP_FILENAME" >&2
    exit 2
  }
  trainer_args+=(--trainer-config.tunableop-filename "$TUNABLEOP_FILENAME")
fi

cd "$OPENDM_ROOT"
exec "$PYTHON" -m torch.distributed.run \
  --nproc_per_node "$NPROC" \
  --master_addr 127.0.0.1 \
  --master_port "$MASTER_PORT" \
  "$PROJECT_ROOT/train/dm05_lerobot.py" \
  --task train \
  --model-config.model-name-or-path "$BASE_MODEL" \
  --model-config.chunk-size 16 \
  --model-config.no-ae-gradient-checkpointing \
  --data-config.lerobot-path "$TRAIN_DATASET" \
  --data-config.dataset-name "$DATASET_NAME" \
  --data-config.action-dim 16 \
  --data-config.norm-stats-root "$NORM_ROOT" \
  --inference-config.output-action-dim 16 \
  --optimizer-config.base-lr 5e-4 \
  --optimizer-config.warmup-steps 500 \
  --trainer-config.output-dir "$OUTPUT_DIR" \
  --trainer-config.num-train-steps "$MAX_STEPS" \
  --trainer-config.save-steps "$SAVE_STEPS" \
  --trainer-config.per-device-train-batch-size "$PER_DEVICE_BATCH" \
  --trainer-config.gradient-accumulation-steps "$GRADIENT_ACCUMULATION" \
  --trainer-config.dataloader-num-workers "$DATALOADER_NUM_WORKERS" \
  --trainer-config.dataloader-prefetch-factor 2 \
  --trainer-config.no-save-only-model \
  --trainer-config.fsdp1 False \
  "${trainer_args[@]}"
