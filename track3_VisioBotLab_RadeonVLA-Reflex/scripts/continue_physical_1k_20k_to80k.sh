#!/usr/bin/env bash
# Guard the cumulative 50K evaluation milestone, then continue Physical-1K to cumulative 80K.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

PYTHON_BIN="${PYTHON_BIN:-/workspace/radeonvla-venv/bin/python}"
REPO_ID="${REPO_ID:-visiobot/radeonvla-reflex-physical-1k}"
DATASET_ROOT="${DATASET_ROOT:-datasets/radeonvla_reflex_physical_1k}"
SOURCE_COMMIT="${SOURCE_COMMIT:-1f0612bfbb8980ada45769517853f79d5b430046}"
VLM_SNAPSHOT="${VLM_SNAPSHOT:-/workspace/hf-cache/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots/7b375e1b73b11138ff12fe22c8f2822d8fe03467}"
PHASE1_OUTPUT="${PHASE1_OUTPUT:-outputs/train/smolvla_radeonvla_reflex_physical_1k_continue_20k_to80k_v2}"
PHASE1_LOG="${PHASE1_LOG:-${PHASE1_OUTPUT}.log}"
PHASE2_OUTPUT="${PHASE2_OUTPUT:-outputs/train/smolvla_radeonvla_reflex_physical_1k_continue_50k_to80k}"

CHECKPOINT_50="$PHASE1_OUTPUT/checkpoints/030000/pretrained_model"
CHECKPOINT_80="$PHASE2_OUTPUT/checkpoints/030000/pretrained_model"
EVAL_50="artifacts/evaluation.physical_1k_cumulative_50k_collected_five_fruit.json"
EVAL_80_FIVE="artifacts/evaluation.physical_1k_cumulative_80k_collected_five_fruit.json"
EVAL_80_FULL="artifacts/evaluation.physical_1k_cumulative_80k_collected_basic20.json"
DECISION_JSON="artifacts/physical_1k_cumulative_80k_release_decision.json"
EVAL_TASKS=(apple_blue_left banana_white_left lemon_blue_right orange_white_right plum_white_left)

export PYTHONPATH=src
export PYTHONUNBUFFERED=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1

[[ -f "$VLM_SNAPSHOT/model.safetensors" ]] || die "VLM weights missing: $VLM_SNAPSHOT"
[[ -f "$VLM_SNAPSHOT/processor_config.json" ]] || die "VLM processor missing: $VLM_SNAPSHOT"

checkpoint_step() {
  local policy_path=$1
  "$PYTHON_BIN" -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["step"])' \
    "$(dirname "$policy_path")/training_state/training_step.json"
}

checkpoint_sha() {
  "$PYTHON_BIN" -c \
    'import sys; from radeonvla.artifact_io import sha256_path; print(sha256_path(sys.argv[1]))' \
    "$1"
}

wait_for_50k() {
  section "Wait for cumulative 50K checkpoint"
  while true; do
    if [[ -f "$CHECKPOINT_50/model.safetensors" ]] \
      && [[ -f "$(dirname "$CHECKPOINT_50")/training_state/training_step.json" ]] \
      && [[ "$(checkpoint_step "$CHECKPOINT_50")" == "30000" ]] \
      && ! pgrep -f 'lerobot_train.*continue_20k_to80k_v2' >/dev/null; then
      break
    fi
    if ! pgrep -f 'lerobot_train.*continue_20k_to80k_v2' >/dev/null; then
      tail -n 80 "$PHASE1_LOG" >&2 || true
      die "20K→50K training stopped without a complete stage-30000 checkpoint"
    fi
    log "20K→50K training is still active"
    sleep 30
  done
  ok "Cumulative 50K checkpoint is complete: $CHECKPOINT_50"
}

vendor_checkpoint_assets() {
  local policy_path=$1
  "$PYTHON_BIN" -m radeonvla.vendor_vlm_assets \
    --policy-path "$policy_path" \
    --source "$VLM_SNAPSHOT"
}

run_five_fruit_eval() {
  local policy_path=$1
  local output=$2
  local seed_start=$3
  local sha
  sha="$(checkpoint_sha "$policy_path")"
  "$PYTHON_BIN" -m radeonvla.evaluate \
    --policy-path "$policy_path" \
    --repo-id "$REPO_ID" \
    --dataset-root "$DATASET_ROOT" \
    --tasks "${EVAL_TASKS[@]}" \
    --episodes-per-task 1 \
    --seed-start "$seed_start" \
    --max-retries 0 \
    --max-steps 600 \
    --instruction-source collected \
    --save-video \
    --checkpoint-sha256 "$sha" \
    --git-commit "$SOURCE_COMMIT" \
    --output "$output"
}

wait_for_50k
vendor_checkpoint_assets "$CHECKPOINT_50"

section "Evaluate cumulative 50K with exact collected language"
run_five_fruit_eval "$CHECKPOINT_50" "$EVAL_50" 50020

section "Continue cumulative 50K to cumulative 80K"
if [[ ! -f "$CHECKPOINT_80/model.safetensors" ]]; then
  [[ ! -e "$PHASE2_OUTPUT" ]] || die "Incomplete phase-2 output already exists: $PHASE2_OUTPUT"
  "$PYTHON_BIN" -m radeonvla.train_policy smolvla \
    --repo-id "$REPO_ID" \
    --dataset-root "$DATASET_ROOT" \
    --policy-path "$CHECKPOINT_50" \
    --name smolvla_radeonvla_reflex_physical_1k_continue_50k_to80k \
    --output-dir "$PHASE2_OUTPUT" \
    --steps 30000 \
    --batch-size 4 \
    --save-freq 10000 \
    --log-freq 200 \
    --num-workers 4 \
    --device cuda \
    -- \
    --policy.vlm_model_name="$VLM_SNAPSHOT" \
    --policy.optimizer_lr=0.00001 \
    --policy.scheduler_warmup_steps=500 \
    --policy.scheduler_decay_steps=30000 \
    --policy.scheduler_decay_lr=0.0000025
fi
[[ "$(checkpoint_step "$CHECKPOINT_80")" == "30000" ]] \
  || die "Cumulative 80K checkpoint has an unexpected training step"
vendor_checkpoint_assets "$CHECKPOINT_80"

section "Evaluate cumulative 80K with exact collected language"
run_five_fruit_eval "$CHECKPOINT_80" "$EVAL_80_FIVE" 50020
FINAL_SHA="$(checkpoint_sha "$CHECKPOINT_80")"
"$PYTHON_BIN" -m radeonvla.evaluate \
  --policy-path "$CHECKPOINT_80" \
  --repo-id "$REPO_ID" \
  --dataset-root "$DATASET_ROOT" \
  --suite basic \
  --episodes-per-task 1 \
  --seed-start 51000 \
  --max-retries 0 \
  --max-steps 600 \
  --instruction-source collected \
  --checkpoint-sha256 "$FINAL_SHA" \
  --git-commit "$SOURCE_COMMIT" \
  --output "$EVAL_80_FULL"

section "Record Hugging Face update recommendation"
"$PYTHON_BIN" - "$EVAL_50" "$EVAL_80_FIVE" "$EVAL_80_FULL" "$DECISION_JSON" "$CHECKPOINT_80" "$FINAL_SHA" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from radeonvla.artifact_io import atomic_write_json

mid_path, final_five_path, final_full_path, output_path, policy_path, checkpoint_sha = sys.argv[1:]

def rate(path: str) -> float:
    return float(json.loads(Path(path).read_text(encoding="utf-8"))["summary"]["final_success"])

mid_rate = rate(mid_path)
final_five_rate = rate(final_five_path)
final_full_rate = rate(final_full_path)
recommend_update = final_five_rate > 0.4 and final_full_rate >= 0.6
atomic_write_json(
    output_path,
    {
        "created_at": datetime.now(UTC).isoformat(),
        "cumulative_50k_five_fruit_success": mid_rate,
        "cumulative_80k_five_fruit_success": final_five_rate,
        "cumulative_80k_basic20_success": final_full_rate,
        "existing_huggingface_20k_five_fruit_success": 0.4,
        "recommended_action": "update_huggingface" if recommend_update else "keep_existing_revision",
        "recommendation_rule": "80K five-fruit > 40% and 80K basic20 >= 60%",
        "policy_path": policy_path,
        "checkpoint_sha256": checkpoint_sha,
        "evidence": [mid_path, final_five_path, final_full_path],
    },
)
print(f"[decision] wrote {output_path}; recommend_update={recommend_update}")
PY

ok "Cumulative 80K training, milestone evaluations, and release recommendation complete"
