#!/usr/bin/env bash
# If cumulative 100K misses the gate, collect another strict 1K and train 100K more steps.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

PYTHON_BIN="${PYTHON_BIN:-/workspace/radeonvla-venv/bin/python}"
SOURCE_COMMIT="${SOURCE_COMMIT:?Set SOURCE_COMMIT to the audited collection-code revision}"
VLM_SNAPSHOT="${VLM_SNAPSHOT:-/workspace/hf-cache/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots/7b375e1b73b11138ff12fe22c8f2822d8fe03467}"
DECISION_100="${DECISION_100:-artifacts/physical_1k_cumulative_100k_release_decision.json}"
OUTPUT_100="${OUTPUT_100:-outputs/train/smolvla_radeonvla_reflex_physical_1k_continue_80k_to100k}"
CHECKPOINT_100="$OUTPUT_100/checkpoints/020000/pretrained_model"

ORIGINAL_REPO_ID="${ORIGINAL_REPO_ID:-visiobot/radeonvla-reflex-physical-1k}"
ORIGINAL_ROOT="${ORIGINAL_ROOT:-datasets/radeonvla_reflex_physical_1k}"
ADDITIONAL_REPO_ID="${ADDITIONAL_REPO_ID:-visiobot/radeonvla-reflex-physical-additional-1k}"
ADDITIONAL_ROOT="${ADDITIONAL_ROOT:-datasets/radeonvla_reflex_physical_additional_1k}"
COMBINED_REPO_ID="${COMBINED_REPO_ID:-visiobot/radeonvla-reflex-physical-2k}"
COMBINED_ROOT="${COMBINED_ROOT:-datasets/radeonvla_reflex_physical_2k}"

OUTPUT_200="${OUTPUT_200:-outputs/train/smolvla_radeonvla_reflex_physical_2k_continue_100k_to200k}"
CHECKPOINT_200="$OUTPUT_200/checkpoints/100000/pretrained_model"
EVAL_200_FIVE="artifacts/evaluation.physical_2k_cumulative_200k_collected_five_fruit.json"
EVAL_200_FULL="artifacts/evaluation.physical_2k_cumulative_200k_collected_basic20.json"
DECISION_200="artifacts/physical_2k_cumulative_200k_release_decision.json"
EVAL_TASKS=(apple_blue_left banana_white_left lemon_blue_right orange_white_right plum_white_left)

SHARD_NAMES=(apple banana lemon orange plum supplement)
SHARD_SEEDS=(71000 72000 73000 74000 75000 76000)
SHARD_QUOTAS=(48 48 48 48 48 2)

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

decision_passed() {
  local path=$1
  "$PYTHON_BIN" -c \
    'import json,sys; raise SystemExit(0 if json.load(open(sys.argv[1]))["gate_passed"] else 1)' \
    "$path"
}

wait_for_100k_decision() {
  section "Wait for cumulative 100K gate decision"
  while [[ ! -f "$DECISION_100" ]]; do
    if ! pgrep -f '[c]ontinue_physical_1k_80k_to100k.sh' >/dev/null \
      && ! pgrep -f 'lerobot_train.*continue_80k_to100k' >/dev/null; then
      die "100K workflow stopped without a gate decision: $DECISION_100"
    fi
    log "Cumulative 100K training/evaluation is still active"
    sleep 30
  done
}

shard_root() {
  printf 'datasets/radeonvla_reflex_physical_additional_1k_shard_%s' "$1"
}

shard_repo_id() {
  printf 'visiobot/radeonvla-reflex-physical-additional-1k-shard-%s' "$1"
}

shard_tasks() {
  case "$1" in
    apple) printf '%s\n' apple_blue_left apple_blue_right apple_white_left apple_white_right ;;
    banana) printf '%s\n' banana_blue_left banana_blue_right banana_white_left banana_white_right ;;
    lemon) printf '%s\n' lemon_blue_left lemon_blue_right lemon_white_left lemon_white_right ;;
    orange) printf '%s\n' orange_blue_left orange_blue_right orange_white_left orange_white_right ;;
    plum) printf '%s\n' plum_blue_left plum_blue_right plum_white_left plum_white_right ;;
    supplement) return 0 ;;
    *) die "Unknown shard name: $1" ;;
  esac
}

launch_shard() {
  local name=$1
  local seed=$2
  local quota=$3
  local root repo_id staging log_path
  local -a args tasks
  root="$(shard_root "$name")"
  repo_id="$(shard_repo_id "$name")"
  staging="$(dirname "$root")/.$(basename "$root").inprogress"
  log_path="outputs/physical_additional_1k_shard_${name}.log"

  if [[ -f "$root/recording_manifest.json" ]]; then
    log "Additional shard $name is already complete"
    return
  fi
  if pgrep -f "radeonvla.record_dataset.*$root" >/dev/null; then
    log "Additional shard $name is already active"
    return
  fi

  args=(
    -m radeonvla.record_dataset
    --backend amdgpu
    --episodes 20
    --episodes-per-task "$quota"
    --repo-id "$repo_id"
    --dataset-root "$root"
    --seed "$seed"
    --max-attempts 2000
    --max-fail-streak 5
    --require-coverage
    --dr-appearance
    --dr-object-color
    --dr-rebuild-every 20
    --dr-runtime
  )
  if [[ "$name" == "supplement" ]]; then
    args+=(--suite basic)
  else
    mapfile -t tasks < <(shard_tasks "$name")
    args+=(--tasks "${tasks[@]}")
  fi
  if [[ -d "$staging" ]]; then
    args+=(--resume-incomplete)
  fi

  log "Launching additional shard $name at seed $seed with per-task quota $quota"
  nohup env \
    PYTHONPATH=src \
    PYTHONUNBUFFERED=1 \
    SOURCE_COMMIT="$SOURCE_COMMIT" \
    "$PYTHON_BIN" "${args[@]}" \
    >"$log_path" 2>&1 < /dev/null &
  echo "$!" >"outputs/physical_additional_1k_shard_${name}.pid"
}

wait_for_shards() {
  section "Wait for six additional strict-physics shards"
  while true; do
    local incomplete=0
    local -a status=()
    local index name root progress successes
    for index in "${!SHARD_NAMES[@]}"; do
      name="${SHARD_NAMES[$index]}"
      root="$(shard_root "$name")"
      progress="$(dirname "$root")/.$(basename "$root").inprogress/recording_progress.json"
      if [[ -f "$root/recording_manifest.json" ]]; then
        status+=("$name=complete")
        continue
      fi
      incomplete=$((incomplete + 1))
      if [[ -f "$progress" ]]; then
        successes="$($PYTHON_BIN -c 'import json,sys; print(json.load(open(sys.argv[1]))["successes"])' "$progress")"
        status+=("$name=$successes")
      else
        status+=("$name=starting")
      fi
      pgrep -f "radeonvla.record_dataset.*$root" >/dev/null \
        || die "Additional shard $name stopped before publication"
    done
    log "${status[*]}"
    [[ "$incomplete" -eq 0 ]] && return
    sleep 30
  done
}

merge_and_validate_datasets() {
  section "Merge and validate the additional Physical-1K"
  local -a shard_roots=()
  local name
  for name in "${SHARD_NAMES[@]}"; do
    shard_roots+=("$(shard_root "$name")")
  done
  if [[ ! -d "$ADDITIONAL_ROOT" ]]; then
    "$PYTHON_BIN" -m radeonvla.merge_dataset_shards \
      --sources "${shard_roots[@]}" \
      --output-root "$ADDITIONAL_ROOT" \
      --repo-id "$ADDITIONAL_REPO_ID" \
      --episodes-per-task 50
  fi
  "$PYTHON_BIN" -m radeonvla.validate_dataset \
    --repo-id "$ADDITIONAL_REPO_ID" \
    --dataset-root "$ADDITIONAL_ROOT" \
    --expected-episodes 1000 \
    --episodes-per-task 50 \
    --require-strict-physics \
    --max-frames 1000 \
    --json artifacts/physical_additional_1k_validation.json

  section "Merge original and additional data into strict Physical-2K"
  if [[ ! -d "$COMBINED_ROOT" ]]; then
    "$PYTHON_BIN" -m radeonvla.merge_dataset_shards \
      --sources "$ORIGINAL_ROOT" "$ADDITIONAL_ROOT" \
      --output-root "$COMBINED_ROOT" \
      --repo-id "$COMBINED_REPO_ID" \
      --episodes-per-task 100
  fi
  "$PYTHON_BIN" -m radeonvla.validate_dataset \
    --repo-id "$COMBINED_REPO_ID" \
    --dataset-root "$COMBINED_ROOT" \
    --expected-episodes 2000 \
    --episodes-per-task 100 \
    --require-strict-physics \
    --max-frames 1000 \
    --json artifacts/physical_2k_validation.json
}

run_five_fruit_eval() {
  local policy_path=$1
  local output=$2
  local sha
  sha="$(checkpoint_sha "$policy_path")"
  "$PYTHON_BIN" -m radeonvla.evaluate \
    --policy-path "$policy_path" \
    --repo-id "$COMBINED_REPO_ID" \
    --dataset-root "$COMBINED_ROOT" \
    --tasks "${EVAL_TASKS[@]}" \
    --episodes-per-task 1 \
    --seed-start 50020 \
    --max-retries 0 \
    --max-steps 600 \
    --instruction-source collected \
    --save-video \
    --checkpoint-sha256 "$sha" \
    --git-commit "$SOURCE_COMMIT" \
    --output "$output"
}

train_and_evaluate_2k() {
  section "Train 100K additional steps on strict Physical-2K"
  [[ -f "$CHECKPOINT_100/model.safetensors" ]] || die "Cumulative 100K checkpoint missing"
  [[ "$(checkpoint_step "$CHECKPOINT_100")" == "20000" ]] \
    || die "Cumulative 100K checkpoint has an unexpected training step"
  if [[ ! -f "$CHECKPOINT_200/model.safetensors" ]]; then
    [[ ! -e "$OUTPUT_200" ]] || die "Incomplete Physical-2K training output exists: $OUTPUT_200"
    "$PYTHON_BIN" -m radeonvla.train_policy smolvla \
      --repo-id "$COMBINED_REPO_ID" \
      --dataset-root "$COMBINED_ROOT" \
      --policy-path "$CHECKPOINT_100" \
      --name smolvla_radeonvla_reflex_physical_2k_continue_100k_to200k \
      --output-dir "$OUTPUT_200" \
      --steps 100000 \
      --batch-size 4 \
      --save-freq 20000 \
      --log-freq 500 \
      --num-workers 4 \
      --device cuda \
      -- \
      --policy.vlm_model_name="$VLM_SNAPSHOT" \
      --policy.optimizer_lr=0.00001 \
      --policy.scheduler_warmup_steps=1000 \
      --policy.scheduler_decay_steps=100000 \
      --policy.scheduler_decay_lr=0.0000025
  fi
  [[ "$(checkpoint_step "$CHECKPOINT_200")" == "100000" ]] \
    || die "Cumulative 200K checkpoint has an unexpected training step"
  vendor_checkpoint_assets "$CHECKPOINT_200"

  section "Evaluate cumulative 200K with exact collected language"
  run_five_fruit_eval "$CHECKPOINT_200" "$EVAL_200_FIVE"
  local final_sha
  final_sha="$(checkpoint_sha "$CHECKPOINT_200")"
  "$PYTHON_BIN" -m radeonvla.evaluate \
    --policy-path "$CHECKPOINT_200" \
    --repo-id "$COMBINED_REPO_ID" \
    --dataset-root "$COMBINED_ROOT" \
    --suite basic \
    --episodes-per-task 1 \
    --seed-start 51000 \
    --max-retries 0 \
    --max-steps 600 \
    --instruction-source collected \
    --checkpoint-sha256 "$final_sha" \
    --git-commit "$SOURCE_COMMIT" \
    --output "$EVAL_200_FULL"

  "$PYTHON_BIN" - "$EVAL_200_FIVE" "$EVAL_200_FULL" "$DECISION_200" "$CHECKPOINT_200" "$final_sha" <<'PY'
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
        "cumulative_200k_five_fruit_success": five_rate,
        "cumulative_200k_basic20_success": full_rate,
        "gate_passed": passed,
        "recommended_action": "update_huggingface" if passed else "keep_existing_revision",
        "recommendation_rule": "200K five-fruit > 40% and 200K basic20 >= 60%",
        "policy_path": policy_path,
        "checkpoint_sha256": checkpoint_sha,
        "evidence": [
            "artifacts/physical_additional_1k_validation.json",
            "artifacts/physical_2k_validation.json",
            five_path,
            full_path,
        ],
    },
)
print(f"[decision] wrote {output_path}; gate_passed={passed}")
PY
}

wait_for_100k_decision
if decision_passed "$DECISION_100"; then
  ok "Cumulative 100K passed the gate; additional data collection is not needed"
  exit 0
fi

section "Cumulative 100K missed the gate; launch additional Physical-1K collection"
for index in "${!SHARD_NAMES[@]}"; do
  launch_shard "${SHARD_NAMES[$index]}" "${SHARD_SEEDS[$index]}" "${SHARD_QUOTAS[$index]}"
done
wait_for_shards
merge_and_validate_datasets
train_and_evaluate_2k

ok "Conditional additional-1K collection and 100K-step Physical-2K training workflow complete"
