#!/usr/bin/env bash
# Wait for the modelscope resume to finish, verify both artifacts, then run the
# single-task 20-episode SmolVLA SFT (smoke check first, then the full run).
set -u

ROOT=/workspace/QVGM
DATASET=/workspace/libero_spatial_image
CHECKPOINT=/workspace/smolvla_base
MODEL_BYTES=906712520
DATA_FILES=69

cd "$ROOT" || exit 1

for _ in $(seq 1 240); do
  files=$(find "$DATASET/data" -name '*.parquet' | wc -l)
  model=$(stat -c %s "$CHECKPOINT/model.safetensors" 2>/dev/null || echo 0)
  if [ "$files" -ge "$DATA_FILES" ] && [ "$model" -eq "$MODEL_BYTES" ]; then
    break
  fi
  if ! pgrep -f "modelscope download" > /dev/null; then
    echo "[wait] modelscope exited early: files=$files model=$model" >&2
    if [ "$model" -ne "$MODEL_BYTES" ] || [ "$files" -lt "$DATA_FILES" ]; then
      echo "[wait] restarting resume" >&2
      nohup /workspace/.modelscope-venv/bin/modelscope download --dataset lerobot/libero_spatial_image \
        --local_dir "$DATASET" >> /tmp/ms_libero.log 2>&1 &
      nohup /workspace/.modelscope-venv/bin/modelscope download --model lerobot/smolvla_base \
        --local_dir "$CHECKPOINT" >> /tmp/ms_smolvla.log 2>&1 &
    fi
  fi
  sleep 30
done

files=$(find "$DATASET/data" -name '*.parquet' | wc -l)
model=$(stat -c %s "$CHECKPOINT/model.safetensors" 2>/dev/null || echo 0)
echo "[verify] data shards=$files/$DATA_FILES model.safetensors=$model/$MODEL_BYTES"
if [ "$files" -lt "$DATA_FILES" ] || [ "$model" -ne "$MODEL_BYTES" ]; then
  echo "[verify] incomplete, not launching SFT" >&2
  exit 1
fi

PY="$ROOT/.venv-rocm/bin/python"
echo "[smoke] 30 steps"
"$PY" scripts/train_smolvla_libero_task0.py \
  --config configs/experiments/lerobot_stove_20ep_smoke.yaml 2>&1 | tail -25
smoke=${PIPESTATUS[0]}
if [ "$smoke" -ne 0 ]; then
  echo "[smoke] failed with $smoke" >&2
  exit "$smoke"
fi

echo "[sft] 6000 steps"
exec "$PY" scripts/train_smolvla_libero_task0.py \
  --config configs/experiments/lerobot_stove_20ep_sft.yaml
