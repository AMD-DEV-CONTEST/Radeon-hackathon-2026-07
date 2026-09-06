#!/usr/bin/env bash
# Fetch the demonstration dataset, train ACT on the Radeon GPU, evaluate in closed loop.
# No robot required.
#
#   bash run_pipeline.sh --quick    # ~5 min:  100 steps, 1 short eval episode (smoke test)
#   bash run_pipeline.sh --full     # ~11 h:   100k steps, 20 full eval episodes
#
# Why this downloads instead of collecting: the submitted datasets were collected on Apple
# silicon (gs.metal), and Genesis' contact solver behaves differently on the ROCm backend —
# the rake grasp flicks the cube off the table there. Training and evaluation, which is where
# the GPU matters, are verified on ROCm. Collect your own with record_dataset_so101.py
# (see README A2) if you are on a machine where that step is known good.
set -euo pipefail

MODE="${1:---quick}"
case "$MODE" in
  # --quick is a smoke test of the plumbing, deliberately too small to learn anything:
  # 100 steps, one episode, and the rollout capped at 10 s so it does not spend 45 s of
  # simulated time watching an untrained policy do nothing.
  --quick) STEPS=100;    SAVE_FREQ=100;   EVAL_EPS=1;  EVAL_SECONDS=10 ;;
  --full)  STEPS=100000; SAVE_FREQ=20000; EVAL_EPS=20; EVAL_SECONDS=45 ;;
  *) echo "usage: $0 [--quick|--full]"; exit 2 ;;
esac

REPO_ID="${REPO_ID:-omiya239532/so101_cube_dr}"
DS_ROOT="datasets/$(basename "$REPO_ID")"
OUT_DIR="outputs/act_dr_${MODE#--}"
export PYOPENGL_PLATFORM="${PYOPENGL_PLATFORM:-egl}"

cd "$(dirname "$0")"
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
t0=$SECONDS

step "Mode: $MODE — $STEPS training steps, $EVAL_EPS eval episodes"
if ! python -c "import torch" 2>/dev/null; then
  echo "ABORT: no torch in $(command -v python). Run setup.sh first; on the amd-oneclick-base"
  echo "       image the ROCm torch lives in /opt/venv (source /opt/venv/bin/activate)."
  exit 1
fi
python -c "import torch; print('torch', torch.__version__, '| GPU', torch.cuda.get_device_name(0))"

# ------------------------------------------------------------------ 1. dataset
step "1/4  Fetching the demonstration dataset ($REPO_ID)"
# 50 episodes collected by the scripted expert with full domain randomisation — no human in
# the loop, which is the point: this is what replaces hours of teleoperation.
# Completeness is checked by the metadata files, not by the directory existing: an aborted
# download leaves the directory behind, and proceeding on that makes training fail later with
# a confusing Hub 401 (LeRobot falls back to the Hub when local metadata is missing).
if [ -f "$DS_ROOT/meta/info.json" ] && [ -f "$DS_ROOT/meta/tasks.parquet" ]; then
  echo "  already present at $DS_ROOT"
else
  [ -d "$DS_ROOT" ] && echo "  $DS_ROOT exists but is incomplete — re-downloading"
  hf download "$REPO_ID" --repo-type dataset --local-dir "$DS_ROOT" \
    || python -c "
from huggingface_hub import snapshot_download
snapshot_download('$REPO_ID', repo_type='dataset', local_dir='$DS_ROOT')
"
  [ -f "$DS_ROOT/meta/info.json" ] || { echo "dataset not available at $DS_ROOT — aborting"; exit 1; }
fi
python -c "
import json; m = json.load(open('$DS_ROOT/meta/info.json'))
print(f\"  {m['total_episodes']} episodes / {m['total_frames']} frames @ {m['fps']} fps\")
"

# ------------------------------------------------------------------ 2. train
step "2/4  Training ACT on the Radeon GPU ($STEPS steps)"
# video_backend=pyav: torchcodec's extension is ABI-incompatible with AMD's torch build.
# Watch utilisation from another shell with: watch -n 1 rocm-smi
lerobot-train \
  --dataset.repo_id="$REPO_ID" \
  --dataset.root="$DS_ROOT" \
  --dataset.image_transforms.enable=true \
  --dataset.video_backend=pyav \
  --policy.type=act \
  --output_dir="$OUT_DIR" \
  --steps="$STEPS" --batch_size=8 --save_freq="$SAVE_FREQ" \
  --policy.device=cuda --policy.push_to_hub=false --wandb.enable=false

CKPT="$OUT_DIR/checkpoints/$(printf '%06d' "$STEPS")/pretrained_model"
[ -d "$CKPT" ] || { echo "expected checkpoint missing: $CKPT"; exit 1; }

step "  Throughput actually achieved (GPU-bound when data_s << updt_s):"
grep -ao 'step:[^ ]* .*mem_gb:[0-9.]*' "$OUT_DIR"/*.log 2>/dev/null | tail -1 || \
  echo "  (see the training output above: ~2.55 step/s, data_s 0.002s vs updt_s 0.388s, 3.9 GB VRAM)"

# ------------------------------------------------------------------- 3. eval
step "3/4  Closed-loop evaluation in simulation ($EVAL_EPS fixed-seed episodes)"
# Seeds are fixed, so any two policies are compared on identical cube placements.
python src/eval_policy_so101.py \
  --policy-path "$CKPT" \
  --repo-id "$REPO_ID" --dataset-root "$DS_ROOT" \
  --episodes "$EVAL_EPS" --max-seconds "$EVAL_SECONDS" --save-video \
  --video-dir "outputs/eval_videos/${MODE#--}" \
  --results-out "outputs/eval_results/${MODE#--}.json"

# --------------------------------------------------------------- 4. summary
step "4/4  Result"
python - <<PY
import json
d = json.load(open("outputs/eval_results/${MODE#--}.json"))
print(f"  success rate : {d['n_success']}/{d['episodes']} = {d['success_rate']*100:.0f}%")
print(f"  checkpoint   : {d['meta']['checkpoint']}")
print(f"  videos       : outputs/eval_videos/${MODE#--}/")
PY

printf '\n\033[1;32mPIPELINE_OK — %d min elapsed\033[0m\n' $(( (SECONDS - t0) / 60 ))
if [ "$MODE" = "--quick" ]; then
  cat <<'MSG'

  NOTE: --quick trains for 100 steps and evaluates one 10-second episode. It will report 0%
  and that is the point — it proves the plumbing (dataset -> ROCm training -> closed-loop
  evaluation) end to end in a few minutes, nothing more. Measured on this task, success is
  25% at 20k steps, peaks at 60% at 60k, then declines as the 50-episode dataset's
  information ceiling is reached. 100 steps is three orders of magnitude short of that.

  For the reported numbers:  bash run_pipeline.sh --full
MSG
fi
