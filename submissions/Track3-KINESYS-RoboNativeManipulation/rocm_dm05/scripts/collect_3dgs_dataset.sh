#!/usr/bin/env bash
set -euo pipefail

: "${BIGYM_3DGS_ROOT:?Set BIGYM_3DGS_ROOT}"
: "${PYTHON:?Set PYTHON}"
: "${OFFICIAL_DEMO_DIR:?Set OFFICIAL_DEMO_DIR}"
: "${PRIVILEGED_MANIFEST:?Set PRIVILEGED_MANIFEST}"
: "${OFFICIAL_AUDIT:?Set OFFICIAL_AUDIT}"
: "${VISUAL_SHELL_PROFILE:?Set VISUAL_SHELL_PROFILE}"
: "${OUTPUT_ROOT:?Set OUTPUT_ROOT}"

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REPLAY_ROOT="$BIGYM_3DGS_ROOT/src/bigym/d/replay_generation"
DATASET_ROOT="$OUTPUT_ROOT/lerobot-3dgs-shards"
NUM_SHARDS=${NUM_SHARDS:-8}
AMD_GPU_IDS=${AMD_GPU_IDS:-0}
IFS=',' read -r -a GPUS <<< "$AMD_GPU_IDS"

mkdir -p "$DATASET_ROOT" "$OUTPUT_ROOT/logs"
for ((shard=0; shard<NUM_SHARDS; shard++)); do
  gpu=${GPUS[$((shard % ${#GPUS[@]}))]}
  shard_name=$(printf 'shard-%02d-of-%02d' "$shard" "$NUM_SHARDS")
  HIP_VISIBLE_DEVICES="$gpu" ROCR_VISIBLE_DEVICES="$gpu" \
    MUJOCO_EGL_DEVICE_ID="$gpu" \
    MUJOCO_GL=egl PYOPENGL_PLATFORM=egl \
    TORCH_EXTENSIONS_DIR="$BIGYM_3DGS_ROOT/cache/torch-extensions-gsplat" \
    PYTHONPATH="$REPO_ROOT/collect:$REPLAY_ROOT" \
    "$PYTHON" "$REPO_ROOT/collect/generate_3dgs_dataset.py" \
      --official-dir "$OFFICIAL_DEMO_DIR" \
      --privileged-manifest "$PRIVILEGED_MANIFEST" \
      --official-audit "$OFFICIAL_AUDIT" \
      --visual-shell-profile "$VISUAL_SHELL_PROFILE" \
      --output-root "$DATASET_ROOT" \
      --shard-index "$shard" \
      --num-shards "$NUM_SHARDS" \
      --vcodec h264 \
      > "$OUTPUT_ROOT/logs/$shard_name.log" 2>&1 &
done
wait

"$PYTHON" "$REPO_ROOT/collect/validate_3dgs_dataset.py" \
  --dataset-root "$DATASET_ROOT" \
  --output "$OUTPUT_ROOT/dataset-validation.json"
