#!/usr/bin/env bash
# One-click local development pipeline (CPU-friendly).
# Stages: assets -> env check -> scene -> expert -> record N eps -> validate
#
# Usage:
#   bash scripts/run_all_local.sh
#   EPISODES=10 SUITE=basic bash scripts/run_all_local.sh
#   TASK=seq_banana_white_left_lemon_white_right EPISODES=3 bash scripts/run_all_local.sh
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

BACKEND="${BACKEND:-cpu}"
EPISODES="${EPISODES:-5}"
SUITE="${SUITE:-basic}"
TASK="${TASK:-}"   # if set, record only this task; else cycle suite
REPO_ID="${REPO_ID:-visiobot/radeonvla_local}"
DATASET_ROOT="${DATASET_ROOT:-datasets/radeonvla_local}"
SEED="${SEED:-0}"
OVERWRITE="${OVERWRITE:-0}"
DISCARD_INCOMPLETE="${DISCARD_INCOMPLETE:-0}"

START=$(date +%s)
section "RadeonVLA-Reflex local one-click"
log "ROOT=$ROOT BACKEND=$BACKEND EPISODES=$EPISODES SUITE=$SUITE"

section "1/6 assets"
run_py -m radeonvla.setup_assets

section "2/6 environment"
run_py -m radeonvla.check_env --json docs/environment.local.json

section "3/6 scene smoke"
run_py -m radeonvla.scene --backend "$BACKEND" --steps 40 --save-frames

section "4/6 expert demo"
if [[ -n "$TASK" ]]; then
  run_py -m radeonvla.expert --backend "$BACKEND" --task "$TASK" --episodes 1 --seed "$SEED"
else
  run_py -m radeonvla.expert --backend "$BACKEND" --task banana_white_left --episodes 1 --seed "$SEED"
fi

section "5/6 record dataset ($EPISODES successful episodes)"
RECORD_ARGS=(
  -m radeonvla.record_dataset
  --backend "$BACKEND"
  --episodes "$EPISODES"
  --repo-id "$REPO_ID"
  --dataset-root "$DATASET_ROOT"
  --seed "$SEED"
)
if [[ "$OVERWRITE" == "1" ]]; then
  RECORD_ARGS+=(--overwrite)
fi
if [[ "$DISCARD_INCOMPLETE" == "1" ]]; then
  RECORD_ARGS+=(--discard-incomplete)
fi
if [[ -n "$TASK" ]]; then
  RECORD_ARGS+=(--task "$TASK")
else
  RECORD_ARGS+=(--suite "$SUITE")
  if [[ "$SUITE" == "basic" && "$EPISODES" -ge 20 ]]; then
    RECORD_ARGS+=(--require-coverage)
  fi
fi
run_py "${RECORD_ARGS[@]}"

section "6/6 validate dataset"
run_py -m radeonvla.validate_dataset --repo-id "$REPO_ID" --dataset-root "$DATASET_ROOT"

ok "Local pipeline finished in $(elapsed "$START")s"
log "Dataset: $ROOT/$DATASET_ROOT"
log "Next (on AMD machine): train with this dataset or re-record with --backend amdgpu"
