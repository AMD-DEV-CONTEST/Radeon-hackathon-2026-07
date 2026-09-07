#!/usr/bin/env bash
# Continue the validated cumulative-80K checkpoint to cumulative 100K, then evaluate it.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

PYTHON_BIN="${PYTHON_BIN:-/workspace/radeonvla-venv/bin/python}"
REPO_ID="${REPO_ID:-visiobot/radeonvla-reflex-physical-1k}"
DATASET_ROOT="${DATASET_ROOT:-datasets/radeonvla_reflex_physical_1k}"
SOURCE_COMMIT="${SOURCE_COMMIT:-1f0612bfbb8980ada45769517853f79d5b430046}"
VLM_SNAPSHOT="${VLM_SNAPSHOT:-/workspace/hf-cache/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots/7b375e1b73b11138ff12fe22c8f2822d8fe03467}"
OUTPUT_80="${OUTPUT_80:-outputs/train/smolvla_radeonvla_reflex_physical_1k_continue_50k_to80k}"
OUTPUT_100="${OUTPUT_100:-outputs/train/smolvla_radeonvla_reflex_physical_1k_continue_80k_to100k}"

CHECKPOINT_80="$OUTPUT_80/checkpoints/030000/pretrained_model"
CHECKPOINT_100="$OUTPUT_100/checkpoints/020000/pretrained_model"
EVAL_100_FIVE="artifacts/evaluation.physical_1k_cumulative_100k_collected_five_fruit.json"
EVAL_100_FULL="artifacts/evaluation.physical_1k_cumulative_100k_collected_basic20.json"
DECISION_JSON="artifacts/physical_1k_cumulative_100k_release_decision.json"
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

[[ -f "$CHECKPOINT_80/model.safetensors" ]] || die "Cumulative 80K checkpoint missing"
[[ "$(checkpoint_step "$CHECKPOINT_80")" == "30000" ]] \
  || die "Cumulative 80K checkpoint has an unexpected training step"

section "Continue cumulative 80K to cumulative 100K"
if [[ ! -f "$CHECKPOINT_100/model.safetensors" ]]; then
  [[ ! -e "$OUTPUT_100" ]] || die "Incomplete 80K-to-100K output already exists: $OUTPUT_100"
  "$PYTHON_BIN" -m radeonvla.train_policy smolvla \
    --repo-id "$REPO_ID" \
    --dataset-root "$DATASET_ROOT" \
    --policy-path "$CHECKPOINT_80" \
    --name smolvla_radeonvla_reflex_physical_1k_continue_80k_to100k \
    --output-dir "$OUTPUT_100" \
    --steps 20000 \
    --batch-size 4 \
    --save-freq 10000 \
    --log-freq 200 \
    --num-workers 4 \
    --device cuda \
    -- \
    --policy.vlm_model_name="$VLM_SNAPSHOT" \
    --policy.optimizer_lr=0.000005 \
    --policy.scheduler_warmup_steps=500 \
    --policy.scheduler_decay_steps=20000 \
    --policy.scheduler_decay_lr=0.0000025
fi
[[ "$(checkpoint_step "$CHECKPOINT_100")" == "20000" ]] \
  || die "Cumulative 100K checkpoint has an unexpected training step"
vendor_checkpoint_assets "$CHECKPOINT_100"

section "Evaluate cumulative 100K with exact collected language"
run_five_fruit_eval "$CHECKPOINT_100" "$EVAL_100_FIVE" 50020
FINAL_SHA="$(checkpoint_sha "$CHECKPOINT_100")"
"$PYTHON_BIN" -m radeonvla.evaluate \
  --policy-path "$CHECKPOINT_100" \
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
  --output "$EVAL_100_FULL"

section "Record cumulative 100K gate decision"
"$PYTHON_BIN" - "$EVAL_100_FIVE" "$EVAL_100_FULL" "$DECISION_JSON" "$CHECKPOINT_100" "$FINAL_SHA" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from radeonvla.artifact_io import atomic_write_json

five_path, full_path, output_path, policy_path, checkpoint_sha = sys.argv[1:]


def rate(path: str) -> float:
    return float(json.loads(Path(path).read_text(encoding="utf-8"))["summary"]["final_success"])


five_rate = rate(five_path)
full_rate = rate(full_path)
passed = five_rate > 0.4 and full_rate >= 0.6
atomic_write_json(
    output_path,
    {
        "created_at": datetime.now(UTC).isoformat(),
        "cumulative_100k_five_fruit_success": five_rate,
        "cumulative_100k_basic20_success": full_rate,
        "gate_passed": passed,
        "recommended_action": (
            "update_huggingface" if passed else "collect_additional_1k_and_train_100k"
        ),
        "recommendation_rule": "100K five-fruit > 40% and 100K basic20 >= 60%",
        "policy_path": policy_path,
        "checkpoint_sha256": checkpoint_sha,
        "evidence": [five_path, full_path],
    },
)
print(f"[decision] wrote {output_path}; gate_passed={passed}")
PY

ok "Cumulative 100K training, exact-language evaluations, and gate decision complete"
