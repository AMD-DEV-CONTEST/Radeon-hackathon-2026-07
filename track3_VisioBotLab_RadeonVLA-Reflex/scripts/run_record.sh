#!/usr/bin/env bash
# One-click demonstration recording only.
#
# Usage:
#   bash scripts/run_record.sh                          # basic suite, 20 eps, cpu
#   BACKEND=amdgpu SUITE=basic EPISODES=200 bash scripts/run_record.sh
#   TASK=leftmost_to_left EPISODES=10 bash scripts/run_record.sh
#   DR=1 EPISODES=50 bash scripts/run_record.sh         # enable domain randomization
#   BACKEND=amdgpu EPISODES_PER_TASK=50 DR=1 bash scripts/run_record.sh
#   BACKEND=amdgpu EPISODES_PER_TASK=50 RESUME_INCOMPLETE=1 bash scripts/run_record.sh
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

BACKEND="${BACKEND:-cpu}"
EPISODES="${EPISODES:-20}"
EPISODES_PER_TASK="${EPISODES_PER_TASK:-0}"
SUITE="${SUITE:-basic}"
TASK="${TASK:-}"
REPO_ID="${REPO_ID:-visiobot/radeonvla_${SUITE}}"
DATASET_ROOT="${DATASET_ROOT:-datasets/radeonvla_${SUITE}}"
SEED="${SEED:-0}"
DR="${DR:-0}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-0}"
OVERWRITE="${OVERWRITE:-0}"
DISCARD_INCOMPLETE="${DISCARD_INCOMPLETE:-0}"
RESUME_INCOMPLETE="${RESUME_INCOMPLETE:-0}"

START=$(date +%s)
section "Record demonstrations"
log "backend=$BACKEND suite=$SUITE task=${TASK:-<suite cycle>} episodes=$EPISODES per_task=$EPISODES_PER_TASK"
log "dataset_root=$DATASET_ROOT"

run_py -m radeonvla.setup_assets

ARGS=(
  -m radeonvla.record_dataset
  --backend "$BACKEND"
  --episodes "$EPISODES"
  --repo-id "$REPO_ID"
  --dataset-root "$DATASET_ROOT"
  --seed "$SEED"
)
if [[ "$EPISODES_PER_TASK" != "0" ]]; then
  ARGS+=(--episodes-per-task "$EPISODES_PER_TASK")
fi
if [[ "$OVERWRITE" == "1" ]]; then
  ARGS+=(--overwrite)
fi
if [[ "$DISCARD_INCOMPLETE" == "1" ]]; then
  ARGS+=(--discard-incomplete)
fi
if [[ "$RESUME_INCOMPLETE" == "1" ]]; then
  ARGS+=(--resume-incomplete)
fi
if [[ -n "$TASK" ]]; then
  ARGS+=(--task "$TASK")
else
  ARGS+=(--suite "$SUITE")
  if [[ "$SUITE" == "basic" && "$EPISODES" -ge 20 ]]; then
    ARGS+=(--require-coverage)
    log "Coverage gate: all 20 basic fruit/bowl combinations are required"
  fi
fi
if [[ "$MAX_ATTEMPTS" != "0" ]]; then
  ARGS+=(--max-attempts "$MAX_ATTEMPTS")
fi
if [[ "$DR" == "1" ]]; then
  ARGS+=(--dr-appearance --dr-object-color --dr-runtime)
  log "Domain randomization: ON"
fi

run_py "${ARGS[@]}"
VALIDATE_ARGS=(
  -m radeonvla.validate_dataset
  --repo-id "$REPO_ID"
  --dataset-root "$DATASET_ROOT"
  --require-strict-physics
)
if [[ "$EPISODES_PER_TASK" != "0" ]]; then
  VALIDATE_ARGS+=(--episodes-per-task "$EPISODES_PER_TASK")
fi
run_py "${VALIDATE_ARGS[@]}"

ok "Recording finished in $(elapsed "$START")s -> $DATASET_ROOT"
