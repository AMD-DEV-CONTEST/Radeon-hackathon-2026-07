#!/usr/bin/env bash
# Finish the task-sharded Physical-1K collection and run the held-out AMD pipeline.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

PYTHON_BIN="${PYTHON_BIN:-/workspace/radeonvla-venv/bin/python}"
REPO_ID="${REPO_ID:-visiobot/radeonvla-reflex-physical-1k}"
DATASET_ROOT="${DATASET_ROOT:-datasets/radeonvla_reflex_physical_1k}"
SOURCE_COMMIT="${SOURCE_COMMIT:-dbc12b69e88be787b679bb41cf2026ca43e0eda6}"
TRAIN_STEPS="${TRAIN_STEPS:-20000}"
EVAL_PER_TASK="${EVAL_PER_TASK:-10}"

SHARD_NAMES=(apple banana lemon orange plum supplement)
SHARD_ROOTS=()
for name in "${SHARD_NAMES[@]}"; do
  SHARD_ROOTS+=("datasets/radeonvla_reflex_physical_1k_shard_${name}")
done

section "Wait for six strict Physical-1K shards"
while true; do
  incomplete=0
  status_line=()
  for index in "${!SHARD_NAMES[@]}"; do
    name="${SHARD_NAMES[$index]}"
    root="${SHARD_ROOTS[$index]}"
    manifest="$root/recording_manifest.json"
    progress="datasets/.radeonvla_reflex_physical_1k_shard_${name}.inprogress/recording_progress.json"
    if [[ -f "$manifest" ]]; then
      status_line+=("$name=complete")
    else
      incomplete=$((incomplete + 1))
      if [[ -f "$progress" ]]; then
        successes="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["successes"])' "$progress")"
        status_line+=("$name=$successes")
      else
        status_line+=("$name=starting")
      fi
    fi
  done
  log "${status_line[*]}"
  if [[ "$incomplete" -eq 0 ]]; then
    break
  fi
  if ! pgrep -f 'radeonvla\.record_dataset.*physical_1k_shard' >/dev/null; then
    die "A collection shard stopped before publishing; inspect outputs/physical_1k_shard_*.log"
  fi
  sleep 30
done

section "Merge and strictly validate Physical-1K"
if [[ ! -d "$DATASET_ROOT" ]]; then
  "$PYTHON_BIN" -m radeonvla.merge_dataset_shards \
    --sources "${SHARD_ROOTS[@]}" \
    --output-root "$DATASET_ROOT" \
    --repo-id "$REPO_ID" \
    --episodes-per-task 50
fi
"$PYTHON_BIN" -m radeonvla.validate_dataset \
  --repo-id "$REPO_ID" \
  --dataset-root "$DATASET_ROOT" \
  --expected-episodes 1000 \
  --episodes-per-task 50 \
  --require-strict-physics \
  --max-frames 1000 \
  --json artifacts/physical_1k_validation.json
cp "$DATASET_ROOT/recording_manifest.json" artifacts/physical_1k_manifest.json

section "Run complete AMD train/evaluation pipeline"
SKIP_RECORD=1 \
EPISODES=1000 \
EPISODES_PER_TASK=50 \
TRAIN_STEPS="$TRAIN_STEPS" \
EVAL_PER_TASK="$EVAL_PER_TASK" \
EVAL_SEED_START=50000 \
INTERRUPT_SEED_START=60000 \
PERTURB_SEED_START=60100 \
REPO_ID="$REPO_ID" \
DATASET_ROOT="$DATASET_ROOT" \
TRAIN_OUTPUT=outputs/train/smolvla_radeonvla_reflex_physical_1k \
SOURCE_COMMIT="$SOURCE_COMMIT" \
PYTHON="$PYTHON_BIN" \
  bash scripts/run_full_remote.sh

ok "Physical-1K data, training, evaluation, and benchmark pipeline complete"
