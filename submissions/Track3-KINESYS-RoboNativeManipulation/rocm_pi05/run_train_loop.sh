#!/usr/bin/env bash
# Robust training driver: horizon=20 intermittently segfaults ~step 500-600 on
# gfx1100/jax0.6.0 (faulty gemm-fusion autotuner kernels). This loop restarts
# with --resume from the latest checkpoint (save_interval=100) until the run
# reaches 20000 steps (clean exit 0) or exhausts the attempt budget.
#
# Usage: bash run_train_loop.sh
set -uo pipefail
source ~/miniconda3/etc/profile.d/conda.sh && conda activate pi05
cd /workspace/openpi

MAX_ATTEMPTS=60
EXTRA_XLA="${XLA_FLAGS:-}"

for i in $(seq 1 $MAX_ATTEMPTS); do
  # Always resume from the latest checkpoint (1300 from the prior fresh run).
  # On crash, --resume picks up the most recent save (save_interval=100).
  RESUME_FLAG="--resume"
  echo "=================== ATTEMPT $i / $MAX_ATTEMPTS  $(date '+%H:%M:%S') flag=$RESUME_FLAG ==================="
  PYTHONUNBUFFERED=1 ROCR_VISIBLE_DEVICES=0 \
    XLA_PYTHON_CLIENT_PREALLOCATE=false XLA_PYTHON_CLIENT_MEM_FRACTION=0.99 \
    XLA_FLAGS="--xla_gpu_autotune_level=1 $EXTRA_XLA" \
    python -u train_jax.py \
      --action-dim 16 --action-horizon 20 --model-action-dim 32 \
      --camera-names high l_wrist r_wrist \
      --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
      --wrist-names l_wrist r_wrist \
      --data-dir /workspace/openSource_AMD_AI_DevMaster_Hackathon_202608/bigym-3dgs-light-floor-replay-plan-v2-20260802/dishwasher_unload_cutlery_long \
      --exp-name run1_lora_h20_20k \
      --norm-stats ./assets/dishwasher_unload_cutlery_long \
      --base-checkpoint gs://openpi-assets/checkpoints/pi05_base/params \
      --lora --num-train-steps 20000 --batch-size 4 --save-interval 100 \
      --log-interval 100 --num-workers 0 $RESUME_FLAG \
      > /workspace/notes/train_run1_lora_h20_20k.log 2>&1
  rc=$?
  echo "attempt $i exit=$rc at $(date '+%H:%M:%S')"
  if [ "$rc" -eq 0 ]; then
    echo "TRAINING COMPLETE (exit 0) at attempt $i"
    exit 0
  fi
  # non-zero: crashed; loop resumes from latest checkpoint (--resume)
done
echo "Exhausted $MAX_ATTEMPTS attempts; last exit=$rc"
exit "$rc"
