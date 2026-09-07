#!/usr/bin/env bash
# Full AMD Radeon workflow: check -> record (suite) -> train -> evaluate -> benchmark
#
# Usage:
#   bash scripts/run_full_remote.sh
#   EPISODES=50 TRAIN_STEPS=5000 SUITE=full bash scripts/run_full_remote.sh
#   SKIP_TRAIN=1 CKPT=path/to/pretrained_model bash scripts/run_full_remote.sh
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
BACKEND="${BACKEND:-amdgpu}"
EPISODES="${EPISODES:-200}"
EPISODES_PER_TASK="${EPISODES_PER_TASK:-0}"
TRAIN_STEPS="${TRAIN_STEPS:-10000}"
SUITE="${SUITE:-basic}"
REPO_ID="${REPO_ID:-visiobot/radeonvla_reflex}"
DATASET_ROOT="${DATASET_ROOT:-datasets/radeonvla_reflex}"
TRAIN_OUTPUT="${TRAIN_OUTPUT:-outputs/train/smolvla_$(basename "$DATASET_ROOT")}"
DEVICE="${DEVICE:-cuda}"
BATCH_SIZE="${BATCH_SIZE:-4}"
EVAL_PER_TASK="${EVAL_PER_TASK:-10}"
EVAL_SEED_START="${EVAL_SEED_START:-50000}"
INTERRUPT_SEED_START="${INTERRUPT_SEED_START:-60000}"
PERTURB_SEED_START="${PERTURB_SEED_START:-60100}"
SKIP_TRAIN="${SKIP_TRAIN:-0}"
SKIP_RECORD="${SKIP_RECORD:-0}"
DR="${DR:-1}"
DR_REBUILD_EVERY="${DR_REBUILD_EVERY:-20}"
OVERWRITE="${OVERWRITE:-0}"
DISCARD_INCOMPLETE="${DISCARD_INCOMPLETE:-0}"
RESUME_INCOMPLETE="${RESUME_INCOMPLETE:-0}"
SOURCE_COMMIT="${SOURCE_COMMIT:-}"

START=$(date +%s)
section "Full remote pipeline"
log "HIP_VISIBLE_DEVICES=$HIP_VISIBLE_DEVICES BACKEND=$BACKEND SUITE=$SUITE EPISODES=$EPISODES"
if [[ -n "$SOURCE_COMMIT" && ! "$SOURCE_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  die "SOURCE_COMMIT must be a 40-character hexadecimal git commit"
fi
GIT_COMMIT_ARGS=()
if [[ -n "$SOURCE_COMMIT" ]]; then
  GIT_COMMIT_ARGS+=(--git-commit "$SOURCE_COMMIT")
  log "Source commit: $SOURCE_COMMIT"
fi

section "1 env (strict AMD)"
run_py -m radeonvla.check_env --require-amd --init-genesis --json artifacts/environment.remote.json

section "2 assets + scene + expert smoke"
run_py -m radeonvla.setup_assets
run_py -m radeonvla.scene --backend "$BACKEND" --steps 50 --save-frames
run_py -m radeonvla.expert --backend "$BACKEND" --task banana_white_left --episodes 2
run_py -m radeonvla.expert --backend "$BACKEND" --task seq_banana_white_left_lemon_white_right --episodes 1

section "3 record ($EPISODES successes, suite=$SUITE)"
if [[ "$SKIP_RECORD" != "1" ]]; then
  RECORD_ARGS=(
    -m radeonvla.record_dataset
    --backend "$BACKEND"
    --episodes "$EPISODES"
    --suite "$SUITE"
    --repo-id "$REPO_ID"
    --dataset-root "$DATASET_ROOT"
  )
  if [[ "$EPISODES_PER_TASK" != "0" ]]; then
    RECORD_ARGS+=(--episodes-per-task "$EPISODES_PER_TASK")
  fi
  if [[ "$SUITE" == "basic" && "$EPISODES" -ge 20 ]]; then
    RECORD_ARGS+=(--require-coverage)
  fi
  if [[ "$DR" == "1" ]]; then
    RECORD_ARGS+=(
      --dr-appearance
      --dr-object-color
      --dr-runtime
      --dr-rebuild-every "$DR_REBUILD_EVERY"
    )
  fi
  if [[ "$OVERWRITE" == "1" ]]; then
    RECORD_ARGS+=(--overwrite)
  fi
  if [[ "$DISCARD_INCOMPLETE" == "1" ]]; then
    RECORD_ARGS+=(--discard-incomplete)
  fi
  if [[ "$RESUME_INCOMPLETE" == "1" ]]; then
    RECORD_ARGS+=(--resume-incomplete)
  fi
  run_py "${RECORD_ARGS[@]}"
else
  section "3 record skipped (SKIP_RECORD=1)"
  [[ -d "$DATASET_ROOT" ]] || die "DATASET_ROOT not found: $DATASET_ROOT"
fi
VALIDATE_ARGS=(
  -m radeonvla.validate_dataset
  --repo-id "$REPO_ID"
  --dataset-root "$DATASET_ROOT"
  --require-strict-physics
  --json artifacts/dataset_validation.json
)
if [[ "$EPISODES_PER_TASK" != "0" ]]; then
  VALIDATE_ARGS+=(--episodes-per-task "$EPISODES_PER_TASK")
fi
run_py "${VALIDATE_ARGS[@]}"
if [[ -f "$DATASET_ROOT/recording_manifest.json" ]]; then
  cp "$DATASET_ROOT/recording_manifest.json" artifacts/dataset_manifest.json
fi

CKPT="${CKPT:-}"
if [[ "$SKIP_TRAIN" != "1" ]]; then
  section "4 train SmolVLA ($TRAIN_STEPS steps)"
  run_py -m radeonvla.train_policy smolvla \
    --repo-id "$REPO_ID" \
    --dataset-root "$DATASET_ROOT" \
    --output-dir "$TRAIN_OUTPUT" \
    --steps "$TRAIN_STEPS" \
    --device "$DEVICE" \
    --batch-size "$BATCH_SIZE"
else
  section "4 train skipped (SKIP_TRAIN=1)"
fi

if [[ -z "$CKPT" ]]; then
  CKPT="$(latest_pretrained_model "$TRAIN_OUTPUT")" \
    || die "No pretrained model found below $TRAIN_OUTPUT/checkpoints"
fi
[[ -d "$CKPT" ]] || die "CKPT not found: $CKPT"
log "Resolved checkpoint: $CKPT"
run_py -m radeonvla.vendor_vlm_assets --policy-path "$CKPT"

section "5 evaluate"
[[ -d "$CKPT" ]] || die "Checkpoint missing: $CKPT (set CKPT=... or disable SKIP_TRAIN)"
CKPT_SHA256="$("${PYTHON[@]}" -m radeonvla.artifact_io "$CKPT" | tail -n 1)"
log "Checkpoint SHA256: $CKPT_SHA256"
run_py -m radeonvla.evaluate \
  --policy-path "$CKPT" \
  --repo-id "$REPO_ID" \
  --dataset-root "$DATASET_ROOT" \
  --backend "$BACKEND" \
  --suite "$SUITE" \
  --episodes-per-task "$EVAL_PER_TASK" \
  --seed-start "$EVAL_SEED_START" \
  --checkpoint-sha256 "$CKPT_SHA256" \
  "${GIT_COMMIT_ARGS[@]}" \
  --output artifacts/evaluation.json \
  --save-video

section "6 Reflex interrupt + perturbation demos"
run_py -m radeonvla.evaluate \
  --policy-path "$CKPT" \
  --repo-id "$REPO_ID" \
  --dataset-root "$DATASET_ROOT" \
  --backend "$BACKEND" \
  --tasks banana_white_left \
  --episodes-per-task 1 \
  --seed-start "$INTERRUPT_SEED_START" \
  --interrupt-demo \
  --checkpoint-sha256 "$CKPT_SHA256" \
  "${GIT_COMMIT_ARGS[@]}" \
  --output artifacts/interrupt_evaluation.json \
  --save-video

run_py -m radeonvla.evaluate \
  --policy-path "$CKPT" \
  --repo-id "$REPO_ID" \
  --dataset-root "$DATASET_ROOT" \
  --backend "$BACKEND" \
  --tasks banana_white_left \
  --episodes-per-task 1 \
  --seed-start "$INTERRUPT_SEED_START" \
  --interrupt-demo \
  --disable-reflex \
  --checkpoint-sha256 "$CKPT_SHA256" \
  "${GIT_COMMIT_ARGS[@]}" \
  --output artifacts/baseline_interrupt_evaluation.json

run_py -m radeonvla.evaluate \
  --policy-path "$CKPT" \
  --repo-id "$REPO_ID" \
  --dataset-root "$DATASET_ROOT" \
  --backend "$BACKEND" \
  --tasks banana_white_left lemon_blue_right plum_white_right \
  --episodes-per-task 2 \
  --seed-start "$PERTURB_SEED_START" \
  --perturbation target_shift \
  --perturb-at-step 30 \
  --checkpoint-sha256 "$CKPT_SHA256" \
  "${GIT_COMMIT_ARGS[@]}" \
  --output artifacts/perturbation_evaluation.json \
  --save-video

section "7 benchmark + checksums"
run_py -m radeonvla.benchmark --backend "$BACKEND" --steps 300 \
  --policy-path "$CKPT" --repo-id "$REPO_ID" --dataset-root "$DATASET_ROOT" \
  --output artifacts/benchmark.json

find artifacts -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
  | sort -z | xargs -0 sha256sum > artifacts/SHA256SUMS

ok "Full remote pipeline finished in $(elapsed "$START")s"
log "Checkpoint: $CKPT"
log "Curated evidence: $ROOT/artifacts"
