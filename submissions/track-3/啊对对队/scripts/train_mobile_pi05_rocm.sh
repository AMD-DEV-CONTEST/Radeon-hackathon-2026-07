#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:-${ROOT_DIR}/outputs/mobile-pi05-residual-seed-v1}"
OUTPUT_DIR="${2:-/root/pi05-runs/mobile-pi05-residual-lora-v1}"
DATASET_ROOT="$(realpath -m -- "${DATASET_ROOT}")"
OUTPUT_DIR="$(realpath -m -- "${OUTPUT_DIR}")"
DEFAULT_BASE_MODEL=lerobot/pi05_base
if [[ -f /root/pi05-assets/pi05-base-local/model.safetensors ]]; then
  DEFAULT_BASE_MODEL=/root/pi05-assets/pi05-base-local
fi
BASE_MODEL="${PI05_BASE_MODEL:-${DEFAULT_BASE_MODEL}}"
BASE_REVISION="${PI05_BASE_REVISION:-7de663972b7817d2c4cf2d84c821153dfea772e9}"
STEPS="${MOBILE_PI05_STEPS:-1000}"
BATCH_SIZE="${MOBILE_PI05_BATCH_SIZE:-1}"
TRAINING_ROLE="${MOBILE_PI05_TRAINING_ROLE:-}"
SCHEDULER_WARMUP_STEPS="${MOBILE_PI05_SCHEDULER_WARMUP_STEPS:-0}"
SCHEDULER_DECAY_STEPS="${MOBILE_PI05_SCHEDULER_DECAY_STEPS:-${STEPS}}"
TINY_OVERFIT_PANEL="${MOBILE_PI05_TINY_OVERFIT_PANEL:-}"
ACTION_THRESHOLDS="${MOBILE_PI05_ACTION_THRESHOLDS:-}"
TINY_OVERFIT_GATE="${MOBILE_PI05_TINY_OVERFIT_GATE:-}"
NUM_WORKERS="${MOBILE_PI05_NUM_WORKERS:-0}"
LORA_R="${MOBILE_PI05_LORA_R:-16}"
LORA_ALPHA="${MOBILE_PI05_LORA_ALPHA:-32}"
SAVE_FREQ="${MOBILE_PI05_SAVE_FREQ:-${STEPS}}"
CHUNK_SIZE="${MOBILE_PI05_CHUNK_SIZE:-30}"
N_ACTION_STEPS="${MOBILE_PI05_N_ACTION_STEPS:-10}"
RESUME_CONFIG="${MOBILE_PI05_RESUME_CONFIG:-}"
RESUME_CHECKPOINT_STEP="${MOBILE_PI05_RESUME_CHECKPOINT_STEP:-}"
RESUME_DECAY_STEPS="${MOBILE_PI05_RESUME_DECAY_STEPS:-}"
RESUME_WARMUP_STEPS="${MOBILE_PI05_RESUME_WARMUP_STEPS:-}"
MODE_LOSS_WEIGHT="${MOBILE_PI05_MODE_LOSS_WEIGHT:-1}"
MODE_CE_WEIGHT="${MOBILE_PI05_MODE_CE_WEIGHT:-0}"
STATE_TOKEN="${MOBILE_PI05_STATE_TOKEN:-0}"
MODE_HEAD="${MOBILE_PI05_MODE_HEAD:-0}"
MODE_HEAD_POOLING="${MOBILE_PI05_MODE_HEAD_POOLING:-masked_mean}"
MODE_HEAD_CE_WEIGHT="${MOBILE_PI05_MODE_HEAD_CE_WEIGHT:-0}"
MODE_HEAD_CLASS_WEIGHTS="${MOBILE_PI05_MODE_HEAD_CLASS_WEIGHTS:-}"
STAGE_LOSS_WEIGHTS="${MOBILE_PI05_STAGE_LOSS_WEIGHTS:-}"
MODE_FLOW_LOSS_WEIGHTS="${MOBILE_PI05_MODE_FLOW_LOSS_WEIGHTS:-}"
MODE_FLOW_LOSS_NORMALIZER="${MOBILE_PI05_MODE_FLOW_LOSS_NORMALIZER:-1}"
WRIST_RGBD="${MOBILE_PI05_WRIST_RGBD:-0}"
ACTION_CONTRACT="${MOBILE_PI05_ACTION_CONTRACT:-residual_v1}"
FULL_ACTION_PROJECTIONS="${MOBILE_PI05_FULL_ACTION_PROJECTIONS:-0}"
SAMPLING_MANIFEST="${MOBILE_PI05_SAMPLING_MANIFEST:-}"
TRAIN_STATS="${MOBILE_PI05_TRAIN_STATS:-}"
TRAIN_STATS_MANIFEST="${MOBILE_PI05_TRAIN_STATS_MANIFEST:-}"
if [[ -n "${SAMPLING_MANIFEST}" ]]; then
  SAMPLING_MANIFEST="$(realpath -m -- "${SAMPLING_MANIFEST}")"
fi
if [[ -n "${TRAIN_STATS}" ]]; then
  TRAIN_STATS="$(realpath -m -- "${TRAIN_STATS}")"
fi
if [[ -n "${TRAIN_STATS_MANIFEST}" ]]; then
  TRAIN_STATS_MANIFEST="$(realpath -m -- "${TRAIN_STATS_MANIFEST}")"
fi
if [[ "${ACTION_CONTRACT}" != "residual_v1" && "${ACTION_CONTRACT}" != "absolute_v1" ]]; then
  echo "ERROR: MOBILE_PI05_ACTION_CONTRACT must be residual_v1 or absolute_v1" >&2
  exit 2
fi
if [[ "${WRIST_RGBD}" != "0" && "${WRIST_RGBD}" != "1" ]]; then
  echo "ERROR: MOBILE_PI05_WRIST_RGBD must be 0 or 1" >&2
  exit 2
fi
if [[ "${FULL_ACTION_PROJECTIONS}" != "0" && "${FULL_ACTION_PROJECTIONS}" != "1" ]]; then
  echo "ERROR: MOBILE_PI05_FULL_ACTION_PROJECTIONS must be 0 or 1" >&2
  exit 2
fi
if [[ "${TRAINING_ROLE}" != "smoke" && "${TRAINING_ROLE}" != "tiny_overfit" && "${TRAINING_ROLE}" != "candidate" ]]; then
  echo "ERROR: MOBILE_PI05_TRAINING_ROLE must be smoke, tiny_overfit, or candidate" >&2
  exit 2
fi
if [[ "${TRAINING_ROLE}" != "smoke" && ( "${ACTION_CONTRACT}" != "absolute_v1" || "${FULL_ACTION_PROJECTIONS}" != "1" ) ]]; then
  echo "ERROR: tiny_overfit/candidate training requires absolute_v1 with full action projections" >&2
  exit 2
fi

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export HF_HOME="${HF_HOME:-/root/.cache/huggingface}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
export TOKENIZERS_PARALLELISM=false
export MOBILE_PI05_ACTION_CONTRACT="${ACTION_CONTRACT}"
export MOBILE_PI05_MODE_LOSS_WEIGHT="${MODE_LOSS_WEIGHT}"
export MOBILE_PI05_MODE_CE_WEIGHT="${MODE_CE_WEIGHT}"
export MOBILE_PI05_STATE_TOKEN="${STATE_TOKEN}"
export MOBILE_PI05_MODE_HEAD="${MODE_HEAD}"
export MOBILE_PI05_MODE_HEAD_POOLING="${MODE_HEAD_POOLING}"
export MOBILE_PI05_MODE_HEAD_CE_WEIGHT="${MODE_HEAD_CE_WEIGHT}"
export MOBILE_PI05_MODE_HEAD_CLASS_WEIGHTS="${MODE_HEAD_CLASS_WEIGHTS}"
export MOBILE_PI05_STAGE_LOSS_WEIGHTS="${STAGE_LOSS_WEIGHTS}"
export MOBILE_PI05_MODE_FLOW_LOSS_WEIGHTS="${MODE_FLOW_LOSS_WEIGHTS}"
export MOBILE_PI05_MODE_FLOW_LOSS_NORMALIZER="${MODE_FLOW_LOSS_NORMALIZER}"
export MOBILE_PI05_FULL_ACTION_PROJECTIONS="${FULL_ACTION_PROJECTIONS}"
if [[ -f "${DATASET_ROOT}/PARCEL_SUCCESS_SPLIT.json" ]]; then
  SAMPLING_MANIFEST="${SAMPLING_MANIFEST:-${DATASET_ROOT}/PARCEL_PI05_SAMPLING_MANIFEST.json}"
  TRAIN_STATS="${TRAIN_STATS:-${DATASET_ROOT}/meta/train_stats.json}"
  TRAIN_STATS_MANIFEST="${TRAIN_STATS_MANIFEST:-${DATASET_ROOT}/PARCEL_TRAIN_STATS_MANIFEST.json}"
  test -f "${SAMPLING_MANIFEST}" || {
    echo "ERROR: parcel success training requires a stratified sampling manifest" >&2
    exit 2
  }
  test -f "${TRAIN_STATS}" && test -f "${TRAIN_STATS_MANIFEST}" || {
    echo "ERROR: parcel success training requires balanced train-only normalization stats" >&2
    exit 2
  }
fi
if [[ -n "${TRAIN_STATS}" && ( -z "${TRAIN_STATS_MANIFEST}" || -z "${SAMPLING_MANIFEST}" ) ]]; then
  echo "ERROR: train-only stats require their manifest and sampling manifest" >&2
  exit 2
fi
export MOBILE_PI05_SAMPLING_MANIFEST="${SAMPLING_MANIFEST}"
export MOBILE_PI05_TRAIN_STATS="${TRAIN_STATS}"
export MOBILE_PI05_TRAIN_STATS_MANIFEST="${TRAIN_STATS_MANIFEST}"

cd "${ROOT_DIR}"
launch_audit_dir="$(mktemp -d)"
launch_audit="${launch_audit_dir}/PI05_TRAINING_LAUNCH_AUDIT.json"
resume_staging_dir=""
cleanup_contract_staging() {
  rm -f "${launch_audit}"
  rmdir "${launch_audit_dir}" 2>/dev/null || true
  if [[ -n "${resume_staging_dir}" && -d "${resume_staging_dir}" ]]; then
    rm -f "${resume_staging_dir}/PI05_TRAINING_CONTRACT.json" \
      "${resume_staging_dir}/PI05_RESUME_AUDIT.json"
    rmdir "${resume_staging_dir}" 2>/dev/null || true
  fi
}
trap cleanup_contract_staging EXIT
launch_audit_args=(
  --training-role "${TRAINING_ROLE}"
  --dataset-root "${DATASET_ROOT}"
  --action-contract "${ACTION_CONTRACT}"
  --steps "${STEPS}"
  --scheduler-warmup-steps "${SCHEDULER_WARMUP_STEPS}"
  --scheduler-decay-steps "${SCHEDULER_DECAY_STEPS}"
  --output "${launch_audit}"
)
if [[ "${TRAINING_ROLE}" == "tiny_overfit" ]]; then
  test -n "${TINY_OVERFIT_PANEL}" && test -n "${ACTION_THRESHOLDS}" || {
    echo "ERROR: tiny_overfit requires MOBILE_PI05_TINY_OVERFIT_PANEL and MOBILE_PI05_ACTION_THRESHOLDS" >&2
    exit 2
  }
  launch_audit_args+=(--stage-panel "${TINY_OVERFIT_PANEL}" --action-thresholds "${ACTION_THRESHOLDS}")
elif [[ "${TRAINING_ROLE}" == "candidate" ]]; then
  test -n "${TINY_OVERFIT_GATE}" || {
    echo "ERROR: candidate training requires MOBILE_PI05_TINY_OVERFIT_GATE" >&2
    exit 2
  }
  launch_audit_args+=(--tiny-overfit-gate "${TINY_OVERFIT_GATE}")
fi
python scripts/audit_mobile_pi05_training_launch.py "${launch_audit_args[@]}"

source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh
if [[ "${MOBILE_PI05_ALLOW_CHECKPOINT_CLEANUP:-0}" == "1" ]]; then
  bash scripts/cleanup_old_checkpoints_rocm.sh
else
  echo "checkpoint_cleanup=skipped (set MOBILE_PI05_ALLOW_CHECKPOINT_CLEANUP=1 to opt in)"
fi
python -c "import peft" 2>/dev/null || {
  echo "ERROR: PI0.5 LoRA requires peft>=0.18.0,<1.0.0" >&2
  exit 3
}

test -f "${DATASET_ROOT}/meta/info.json" || {
  echo "ERROR: PI0.5 LeRobotDataset not found: ${DATASET_ROOT}" >&2
  exit 4
}

MOBILE_PI05_MIN_RECOVERY_EPISODES="${MOBILE_PI05_MIN_RECOVERY_EPISODES:-6}"
MOBILE_PI05_MIN_NONZERO_FRAMES="${MOBILE_PI05_MIN_NONZERO_FRAMES:-60}"
MOBILE_PI05_MIN_EPISODES_PER_MODE="${MOBILE_PI05_MIN_EPISODES_PER_MODE:-2}"
DATASET_GATE_ALLOW_ZERO_SEED=0
if [[ "${TRAINING_ROLE}" != "candidate" ]]; then
  DATASET_GATE_ALLOW_ZERO_SEED=1
elif [[ "${MOBILE_PI05_ALLOW_ZERO_SEED:-0}" != "0" ]]; then
  echo "ERROR: candidate training cannot bypass the verified-source dataset gate" >&2
  exit 4
fi
python - "${DATASET_ROOT}" "${MOBILE_PI05_MIN_RECOVERY_EPISODES}" \
  "${MOBILE_PI05_MIN_NONZERO_FRAMES}" "${MOBILE_PI05_MIN_EPISODES_PER_MODE}" \
  "${DATASET_GATE_ALLOW_ZERO_SEED}" "${WRIST_RGBD}" "${ACTION_CONTRACT}" <<'PY'
import json
import os
from pathlib import Path
import sys

from parcel_sorter.mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
)
from parcel_sorter.mobile_pi05_normalization import unsafe_quantile_dimensions
from parcel_sorter.mobile_dataset import (
    infer_mobile_policy_modality,
    mobile_policy_visual_keys,
)
from parcel_sorter.mobile_pi05_research_protocol import independent_source_identity

root = Path(sys.argv[1])
minimum_episodes = int(sys.argv[2])
minimum_frames = int(sys.argv[3])
minimum_per_mode = int(sys.argv[4])
allow_zero_seed = sys.argv[5] == "1"
wrist_rgbd = sys.argv[6] == "1"
action_contract = sys.argv[7]
absolute_contract = action_contract == "absolute_v1"
state_names = (
    MOBILE_PI05_ABSOLUTE_STATE_NAMES if absolute_contract else MOBILE_PI05_STATE_NAMES
)
action_names = (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES
    if absolute_contract
    else MOBILE_PI05_RESIDUAL_ACTION_NAMES
)
manifest_path = root / (
    "PI05_ABSOLUTE_DATASET_MANIFEST.json"
    if absolute_contract
    else "PI05_RESIDUAL_DATASET_MANIFEST.json"
)
if not manifest_path.is_file():
    raise SystemExit("ERROR: PI0.5 dataset manifest is missing for the action contract")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
info = json.loads((root / "meta/info.json").read_text(encoding="utf-8"))
observed_visual_modality = infer_mobile_policy_modality(info.get("features", {}))
required_visual_modality = "rgbd_wrist" if wrist_rgbd else "rgbd"
if observed_visual_modality != required_visual_modality:
    raise SystemExit(
        "ERROR: PI0.5 dataset visual contract mismatch: "
        f"observed={observed_visual_modality}, required={required_visual_modality}"
    )
required_visual_keys = list(mobile_policy_visual_keys(required_visual_modality))
if manifest.get("policy_visual_keys") not in (None, required_visual_keys):
    raise SystemExit("ERROR: PI0.5 residual manifest visual keys mismatch")
stats_path = Path(
    os.environ.get("MOBILE_PI05_TRAIN_STATS") or root / "meta/stats.json"
)
if not stats_path.is_file():
    raise SystemExit("ERROR: PI0.5 dataset normalization stats are missing")
stats = json.loads(stats_path.read_text(encoding="utf-8"))
unsafe_stats = {
    feature: list(unsafe_quantile_dimensions(stats.get(feature, {}), names))
    for feature, names in (
        ("observation.state", state_names),
        ("action", action_names),
    )
}
if any(unsafe_stats.values()):
    raise SystemExit(
        "ERROR: PI0.5 quantile normalization would amplify variable channels: "
        f"{unsafe_stats}"
    )
nonzero_frames = int(
    manifest.get(
        "nonzero_base_command_frames"
        if absolute_contract
        else "nonzero_contact_residual_frames",
        0,
    )
)
recovery_entries = [
    item
    for item in manifest.get("episode_manifests", ())
    if item.get("seed_role")
    == (
        "verified_successful_absolute_action_supervision"
        if absolute_contract
        else "verified_successful_recovery_supervision"
    )
]
independent_recovery_ids = {
    (
        item.get("source_dataset"),
        item.get("source_episode_index"),
        item.get("source_episode_id") or item.get("episode_id"),
    )
    for item in recovery_entries
}
recovery_episodes = len(independent_recovery_ids)
replayed_training_episodes = len(recovery_entries) - recovery_episodes
mode_names = ("top_suction", "side_suction", "cooperative_cradle")
mode_source_identities = {mode: set() for mode in mode_names}
for item in recovery_entries:
    identity = independent_source_identity(item)
    for mode in item.get("grasp_modes", ()):
        if mode in mode_source_identities:
            mode_source_identities[mode].add(identity)
mode_episode_counts = {
    mode: len(identities) for mode, identities in mode_source_identities.items()
}
missing_modes = {
    mode: count
    for mode, count in mode_episode_counts.items()
    if count < minimum_per_mode
}
verified_summary = manifest.get("verified_recovery_summary") or manifest.get(
    "verified_recovery_summaries"
)
mode_conditioning_policy = manifest.get("mode_conditioning_policy")
lift_residual_supervision = manifest.get("lift_residual_supervision")
target_leakage_audit = manifest.get("target_leakage_audit") or {}
if not allow_zero_seed and (
    not verified_summary
    or recovery_episodes < minimum_episodes
    or nonzero_frames < minimum_frames
    or missing_modes
    or mode_conditioning_policy != "hidden_all_stages"
    or (
        not absolute_contract
        and lift_residual_supervision != "smooth_stage_progress_v2"
    )
    or (
        absolute_contract
        and (
            manifest.get("expert_reference_used") is not False
            or int(target_leakage_audit.get("action_derived_state_fields", -1)) != 0
        )
    )
):
    raise SystemExit(
        "ERROR: formal PI0.5 training requires verified, leakage-free recovery data; "
        f"episodes={recovery_episodes}/{minimum_episodes}, "
        f"frames={nonzero_frames}/{minimum_frames}, summary={verified_summary!r}, "
        f"independent_source_counts_by_mode={mode_episode_counts}, "
        f"minimum_independent_sources_per_mode={minimum_per_mode}, "
        f"mode_conditioning={mode_conditioning_policy!r}, "
        f"lift_supervision={lift_residual_supervision!r}"
    )
print(
    json.dumps(
        {
            "pi05_dataset_gate": "passed",
            "action_contract": action_contract,
            "verified_recovery_episodes": recovery_episodes,
            "verified_recovery_episode_instances": len(recovery_entries),
            "replayed_training_episodes": replayed_training_episodes,
            "nonzero_contact_residual_frames": nonzero_frames,
            "nonzero_supervision_kind": (
                "base_command" if absolute_contract else "contact_residual"
            ),
            "independent_source_counts_by_mode": mode_episode_counts,
            "minimum_independent_sources_per_mode": minimum_per_mode,
            "missing_modes": missing_modes,
            "mode_conditioning_policy": mode_conditioning_policy,
            "task_language_policy": manifest.get("task_language_policy", "source_text"),
            "lift_residual_supervision": lift_residual_supervision,
            "target_leakage_audit": target_leakage_audit,
            "zero_seed_override": allow_zero_seed,
            "normalization_stats_policy": manifest.get("normalization_stats_policy"),
            "unsafe_normalization_dimensions": unsafe_stats,
            "policy_visual_modality": required_visual_modality,
            "policy_visual_keys": required_visual_keys,
        }
    )
)
PY

# Both contracts use observable contact/task state and an audited visual
# modality. Absolute v1 emits executable actions without an expert reference.
POLICY_INPUT_FEATURES='{observation.state: {type: STATE, shape: [80]}, observation.images.overhead_rgb: {type: VISUAL, shape: [3, 224, 224]}, observation.images.overhead_depth_rgb: {type: VISUAL, shape: [3, 224, 224]}}'
if [[ "${WRIST_RGBD}" == "1" ]]; then
  POLICY_INPUT_FEATURES='{observation.state: {type: STATE, shape: [80]}, observation.images.overhead_rgb: {type: VISUAL, shape: [3, 224, 224]}, observation.images.overhead_depth_rgb: {type: VISUAL, shape: [3, 224, 224]}, observation.images.left_wrist_rgb: {type: VISUAL, shape: [3, 224, 224]}, observation.images.left_wrist_depth_rgb: {type: VISUAL, shape: [3, 224, 224]}}'
fi
POLICY_OUTPUT_FEATURES='{action: {type: ACTION, shape: [14]}}'
JOB_NAME=mobile-bimanual-pi05-rgbd-residual14-lora-rocm
if [[ "${ACTION_CONTRACT}" == "absolute_v1" ]]; then
  POLICY_OUTPUT_FEATURES='{action: {type: ACTION, shape: [23]}}'
  JOB_NAME=mobile-bimanual-pi05-rgbd-absolute23-lora-rocm
fi
TRAIN_ENTRY=(lerobot-train)
if [[ "${MODE_LOSS_WEIGHT}" != "1" && "${MODE_LOSS_WEIGHT}" != "1.0" ]] || \
  [[ "${MODE_CE_WEIGHT}" != "0" && "${MODE_CE_WEIGHT}" != "0.0" ]] || \
  [[ "${STATE_TOKEN}" == "1" ]] || [[ "${MODE_HEAD}" == "1" ]] || \
  [[ "${MODE_HEAD_CE_WEIGHT}" != "0" && "${MODE_HEAD_CE_WEIGHT}" != "0.0" ]] || \
  [[ -n "${MODE_HEAD_CLASS_WEIGHTS}" ]] || \
  [[ -n "${STAGE_LOSS_WEIGHTS}" ]] || \
  [[ -n "${MODE_FLOW_LOSS_WEIGHTS}" ]] || \
  [[ "${ACTION_CONTRACT}" == "absolute_v1" ]] || \
  [[ "${FULL_ACTION_PROJECTIONS}" == "1" ]] || \
  [[ -n "${SAMPLING_MANIFEST}" ]] || [[ -n "${TRAIN_STATS}" ]]; then
  TRAIN_ENTRY=(python "${ROOT_DIR}/scripts/train_mobile_pi05_weighted_entry.py")
fi

write_training_contract() {
  local contract_output_dir="${1:-${OUTPUT_DIR}}"
  architecture_args=()
  if [[ "${STATE_TOKEN}" == "1" ]]; then
    architecture_args+=(--state-token)
  fi
  if [[ "${MODE_HEAD}" == "1" ]]; then
    architecture_args+=(--mode-head --mode-head-pooling "${MODE_HEAD_POOLING}")
  fi
  if [[ -n "${MODE_HEAD_CLASS_WEIGHTS}" ]]; then
    architecture_args+=(--mode-head-class-weights "${MODE_HEAD_CLASS_WEIGHTS}")
  fi
  if [[ -n "${STAGE_LOSS_WEIGHTS}" ]]; then
    architecture_args+=(--stage-loss-weights "${STAGE_LOSS_WEIGHTS}")
  fi
  if [[ -n "${MODE_FLOW_LOSS_WEIGHTS}" ]]; then
    architecture_args+=(
      --mode-flow-loss-weights "${MODE_FLOW_LOSS_WEIGHTS}"
      --mode-flow-loss-population-normalizer "${MODE_FLOW_LOSS_NORMALIZER}"
    )
  fi
  if [[ "${FULL_ACTION_PROJECTIONS}" == "1" ]]; then
    architecture_args+=(--full-action-projections)
  fi
  if [[ -n "${SAMPLING_MANIFEST}" ]]; then
    architecture_args+=(--sampling-manifest "${SAMPLING_MANIFEST}")
  fi
  if [[ -n "${TRAIN_STATS}" ]]; then
    architecture_args+=(
      --normalization-stats "${TRAIN_STATS}"
      --train-stats-manifest "${TRAIN_STATS_MANIFEST}"
    )
  fi
  python scripts/write_mobile_pi05_training_contract.py \
    --dataset-root "${DATASET_ROOT}" \
    --output-dir "${contract_output_dir}" \
    --base-model "${BASE_MODEL}" \
    --base-revision "${BASE_REVISION}" \
    --chunk-size "${CHUNK_SIZE}" \
    --n-action-steps "${N_ACTION_STEPS}" \
    --training-role "${TRAINING_ROLE}" \
    --requested-training-steps "${STEPS}" \
    --training-batch-size "${BATCH_SIZE}" \
    --scheduler-type cosine_decay \
    --scheduler-warmup-steps "${SCHEDULER_WARMUP_STEPS}" \
    --scheduler-decay-steps "${SCHEDULER_DECAY_STEPS}" \
    --launch-audit "${launch_audit}" \
    "${architecture_args[@]}"
}

if [[ -n "${RESUME_CONFIG}" ]]; then
  test -f "${RESUME_CONFIG}" || {
    echo "ERROR: PI0.5 resume config not found: ${RESUME_CONFIG}" >&2
    exit 5
  }
  if [[ -n "${RESUME_DECAY_STEPS}" && "${RESUME_DECAY_STEPS}" != "${SCHEDULER_DECAY_STEPS}" ]]; then
    echo "ERROR: resume decay steps conflict with the frozen scheduler contract" >&2
    exit 5
  fi
  if [[ -n "${RESUME_WARMUP_STEPS}" && "${RESUME_WARMUP_STEPS}" != "${SCHEDULER_WARMUP_STEPS}" ]]; then
    echo "ERROR: resume warmup steps conflict with the frozen scheduler contract" >&2
    exit 5
  fi
  if [[ ! "${RESUME_CHECKPOINT_STEP}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: resume requires MOBILE_PI05_RESUME_CHECKPOINT_STEP" >&2
    exit 5
  fi
  existing_contract="${OUTPUT_DIR}/PI05_TRAINING_CONTRACT.json"
  existing_launch_audit="${OUTPUT_DIR}/PI05_TRAINING_LAUNCH_AUDIT.json"
  test -f "${existing_contract}" || {
    echo "ERROR: immutable PI0.5 training contract is missing" >&2
    exit 5
  }
  test -f "${existing_launch_audit}" || {
    echo "ERROR: original PI0.5 training launch audit is missing" >&2
    exit 5
  }
  resume_staging_dir="$(mktemp -d)"
  write_training_contract "${resume_staging_dir}"
  resume_audit="${resume_staging_dir}/PI05_RESUME_AUDIT.json"
  resume_audit_target="${OUTPUT_DIR}/PI05_RESUME_AUDIT_STEP_$(printf '%06d' "${RESUME_CHECKPOINT_STEP}").json"
  test ! -e "${resume_audit_target}" || {
    echo "ERROR: resume audit already exists: ${resume_audit_target}" >&2
    exit 5
  }
  python scripts/audit_mobile_pi05_resume_training.py \
    --existing-contract "${existing_contract}" \
    --proposed-contract "${resume_staging_dir}/PI05_TRAINING_CONTRACT.json" \
    --existing-launch-audit "${existing_launch_audit}" \
    --proposed-launch-audit "${launch_audit}" \
    --checkpoint "$(dirname "${RESUME_CONFIG}")" \
    --checkpoint-step "${RESUME_CHECKPOINT_STEP}" \
    --output "${resume_audit}"
  cp "${resume_audit}" "${resume_audit_target}"
  rm -f "${resume_staging_dir}/PI05_TRAINING_CONTRACT.json" "${resume_audit}"
  rmdir "${resume_staging_dir}"
  "${TRAIN_ENTRY[@]}" \
    --config_path="${RESUME_CONFIG}" \
    --resume true \
    --steps "${STEPS}" \
    --save_freq "${SAVE_FREQ}" \
    --policy.scheduler_decay_steps "${SCHEDULER_DECAY_STEPS}" \
    --policy.scheduler_warmup_steps "${SCHEDULER_WARMUP_STEPS}" \
    --wandb.enable false
  exit 0
fi

# LeRobot rejects a new run when output_dir already exists. Stage the immutable
# contract beside the run, then install it as soon as the trainer creates the
# directory and before any checkpoint can be written.
if [[ -e "${OUTPUT_DIR}" ]]; then
  echo "ERROR: new PI0.5 output already exists: ${OUTPUT_DIR}" >&2
  exit 6
fi
contract_staging_dir="$(mktemp -d "${OUTPUT_DIR}.contract-staging.XXXXXX")"
write_training_contract "${contract_staging_dir}"

"${TRAIN_ENTRY[@]}" \
  --dataset.repo_id local/mobile-bimanual-parcel-expert \
  --dataset.root "${DATASET_ROOT}" \
  --dataset.video_backend pyav \
  --dataset.depth_output_unit m \
  --dataset.image_transforms.enable false \
  --policy.type pi05 \
  --policy.pretrained_path "${BASE_MODEL}" \
  --policy.pretrained_revision "${BASE_REVISION}" \
  --policy.device cuda \
  --policy.dtype bfloat16 \
  --policy.use_amp true \
  --policy.push_to_hub false \
  --policy.input_features "${POLICY_INPUT_FEATURES}" \
  --policy.output_features "${POLICY_OUTPUT_FEATURES}" \
  --policy.max_state_dim 96 \
  --policy.max_action_dim 32 \
  --policy.chunk_size "${CHUNK_SIZE}" \
  --policy.n_action_steps "${N_ACTION_STEPS}" \
  --policy.gradient_checkpointing true \
  --policy.freeze_vision_encoder true \
  --peft.method_type LORA \
  --peft.r "${LORA_R}" \
  --peft.lora_alpha "${LORA_ALPHA}" \
  --output_dir "${OUTPUT_DIR}" \
  --job_name "${JOB_NAME}" \
  --batch_size "${BATCH_SIZE}" \
  --num_workers "${NUM_WORKERS}" \
  --steps "${STEPS}" \
  --seed 11 \
  --log_freq 1 \
  --save_checkpoint true \
  --save_freq "${SAVE_FREQ}" \
  --policy.scheduler_decay_steps "${SCHEDULER_DECAY_STEPS}" \
  --policy.scheduler_warmup_steps "${SCHEDULER_WARMUP_STEPS}" \
  --wandb.enable false \
  --env_eval_freq 0 \
  --eval_steps 0 &
training_pid=$!

while [[ ! -d "${OUTPUT_DIR}" ]] && kill -0 "${training_pid}" 2>/dev/null; do
  sleep 0.1
done
if [[ -d "${OUTPUT_DIR}" ]]; then
  contract_tmp="${OUTPUT_DIR}/.PI05_TRAINING_CONTRACT.json.tmp.$$"
  mv "${contract_staging_dir}/PI05_TRAINING_CONTRACT.json" "${contract_tmp}"
  mv "${contract_tmp}" "${OUTPUT_DIR}/PI05_TRAINING_CONTRACT.json"
  cp "${launch_audit}" "${OUTPUT_DIR}/PI05_TRAINING_LAUNCH_AUDIT.json"
  rmdir "${contract_staging_dir}"
  echo "training_contract=installed_before_first_checkpoint"
else
  echo "ERROR: trainer exited before creating output_dir; staged contract preserved at ${contract_staging_dir}" >&2
fi

set +e
wait "${training_pid}"
training_status=$?
set -e
exit "${training_status}"
