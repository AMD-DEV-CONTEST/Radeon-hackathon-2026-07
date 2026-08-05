#!/usr/bin/env bash
# M-FT-3 per-epoch selection: frozen 6-run set (FT2-SELECT protocol),
# mechanical criterion = pass count, tie-break total forbidden steps.
set -u
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"
UV_BIN=${UV_BIN:-uv}
TRAIN=experiment-results/quadrupedal-agility/FT3-TRAIN
OUT=experiment-results/quadrupedal-agility/FT3-SELECT
LOG=$OUT/select.log
mkdir -p "$OUT"

src () {  # name task seed friction ckpt outdir
  CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0} "$UV_BIN" run --project UniLab --no-sync python \
    experiments/neupan_agility/run_source_task.py \
    --task "$2" --seed "$3" --friction "$4" \
    --high-branch student --precision float16 \
    --yaw-source waypoint --onehot-source gt \
    --depth-encoder-checkpoint "$5" --output-dir "$6" \
    >> "$LOG" 2>&1 || echo "RUN_FAILED $6" >> "$LOG"
}
plan () {  # scenario jumpfeed ckpt outdir
  CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0} "$UV_BIN" run --project UniLab --no-sync python \
    experiments/neupan_agility/run_static_2p5d.py \
    --scenario "$1" --jump-feed "$2" --seed 7 \
    --depth-encoder-checkpoint "$3" --output-dir "$4" \
    >> "$LOG" 2>&1 || echo "RUN_FAILED $4" >> "$LOG"
}

for ep in 1 2 3 4 5 6; do
  CKPT=$TRAIN/ft1_depth_encoder_epoch${ep}.pt
  [ -f "$CKPT" ] || { echo "MISSING $CKPT" >> "$LOG"; continue; }
  D=$OUT/ep$ep
  [ -f "$D/frame130/result.json" ]  || src frame130 frame 27 1.3 "$CKPT" "$D/frame130"
  [ -f "$D/tire100/result.json" ]   || src tire100 tire_jump 7 1.0 "$CKPT" "$D/tire100"
  [ -f "$D/seesaw165/result.json" ] || src seesaw165 seesaw 37 1.65 "$CKPT" "$D/seesaw165"
  [ -f "$D/TF/result.json" ]        || plan TF default "$CKPT" "$D/TF"
  [ -f "$D/DW/result.json" ]        || plan DW default "$CKPT" "$D/DW"
  [ -f "$D/TRCM/result.json" ]      || plan TR commit "$CKPT" "$D/TRCM"
  echo "EPOCH_DONE $ep" >> "$LOG"
done
echo "SELECT_DONE" >> "$LOG"
