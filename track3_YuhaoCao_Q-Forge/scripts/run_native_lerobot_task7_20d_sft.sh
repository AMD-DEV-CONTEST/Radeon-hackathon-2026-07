#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/workspace/QVGM"
PYTHON_BIN="$PROJECT_ROOT/.venv-lerobot-native/bin/python"
TRAIN_BIN="$PROJECT_ROOT/.venv-lerobot-native/bin/lerobot-train"
DATASET_ROOT="/workspace/libero_task7_20d_lerobot_v3"
MODEL_ROOT="$PROJECT_ROOT/checkpoints/smolvla_base_libero_native"
OUTPUT_ROOT="/tmp/qvgm_task7_20d/outputs/native_lerobot_smolvla_task7_20d_20k"

export TOKENIZERS_PARALLELISM=false
export ACCELERATE_MIXED_PRECISION=bf16

"$PYTHON_BIN" - <<'PY'
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

root = "/workspace/libero_task7_20d_lerobot_v3"
meta = LeRobotDatasetMetadata("local/libero_spatial_task7_stove_20d", root=root)
assert meta.total_episodes == 20, meta.total_episodes
assert list(meta.tasks.index) == [
    "pick up the black bowl on the stove and place it on the plate"
]
print(
    f"validated native LeRobot 20D dataset: "
    f"{meta.total_episodes} episodes / {meta.total_frames} frames"
)
PY

exec "$TRAIN_BIN" \
  --policy.path="$MODEL_ROOT" \
  --policy.device=cuda \
  --policy.use_amp=true \
  --policy.load_vlm_weights=false \
  --policy.push_to_hub=false \
  --dataset.repo_id=local/libero_spatial_task7_stove_20d \
  --dataset.root="$DATASET_ROOT" \
  --dataset.use_imagenet_stats=false \
  --dataset.video_backend=pyav \
  --output_dir="$OUTPUT_ROOT" \
  --job_name=smolvla_task7_native_20d_20k \
  --steps=20000 \
  --batch_size=64 \
  --num_workers=8 \
  --seed=1000 \
  --log_freq=200 \
  --save_checkpoint=true \
  --save_freq=20000 \
  --eval_freq=0 \
  --wandb.enable=false
