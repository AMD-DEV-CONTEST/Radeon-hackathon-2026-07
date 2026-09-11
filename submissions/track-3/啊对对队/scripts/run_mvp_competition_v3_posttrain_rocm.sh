#!/usr/bin/env bash
# Wait for the fixed-budget competition candidate, then fail closed through
# checkpoint, frozen-panel, and strict pure-VLA rollout gates.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAIN_PID="${1:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT EVIDENCE_DIR [STEP]}"
TRAIN_LOG="${2:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT EVIDENCE_DIR [STEP]}"
RUN_ROOT="${3:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT EVIDENCE_DIR [STEP]}"
EVIDENCE_DIR="${4:?usage: $0 TRAIN_PID TRAIN_LOG RUN_ROOT EVIDENCE_DIR [STEP]}"
STEP="${5:-300}"
PANEL_DATASET_ROOT="/workspace/persistence/parcel-sorter-opt-v1/runs/parcel-pi05-single-box-v14-mvp-incremental-deployment-v2-20260803"
STAGE_PANEL="/workspace/persistence/parcel-sorter-opt-v1/evidence/pi05_vla/full_source_candidate_restart2_20260804/full_source_training_stage_panel.json"
ACTION_THRESHOLDS="${ROOT_DIR}/configs/mobile_pi05_tiny_overfit_action_thresholds_v1.json"
STRICT_DESIGN="${ROOT_DIR}/configs/mobile_pi05_single_box_v14_v7_strict_smoke_3.json"
printf -v CHECKPOINT_STEP '%06d' "${STEP}"
CHECKPOINT="${RUN_ROOT}/checkpoints/${CHECKPOINT_STEP}/pretrained_model"
SCREEN_DIR="${EVIDENCE_DIR}/frozen_panel"
STRICT_OUTPUT="${EVIDENCE_DIR}/strict_pure_vla3"
PYTHON="/workspace/rdna/bin/python"
REQUIRE_DIRECT_ACTION_HEAD="${MOBILE_PI05_REQUIRE_DIRECT_ACTION_HEAD:-0}"
EXPECTED_DIRECT_ACTION_HEAD_MSE_WEIGHT="${MOBILE_PI05_EXPECTED_DIRECT_ACTION_HEAD_MSE_WEIGHT:-}"
EXPECTED_DIRECT_ACTION_TARGET_PROTOCOL="${MOBILE_PI05_EXPECTED_DIRECT_ACTION_TARGET_PROTOCOL:-}"
EXPECTED_MODE_HEAD_CE_WEIGHT="${MOBILE_PI05_EXPECTED_MODE_HEAD_CE_WEIGHT:-2.0}"
EXPECTED_ACTION_LOSS_WEIGHTS="${MOBILE_PI05_EXPECTED_ACTION_LOSS_WEIGHTS:-}"

if [[ ! "${TRAIN_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: TRAIN_PID must be a positive integer" >&2
  exit 2
fi
for path in "${TRAIN_LOG}" "${STAGE_PANEL}" "${ACTION_THRESHOLDS}" "${STRICT_DESIGN}"; do
  test -e "${path}" || {
    echo "ERROR: required immutable input is missing: ${path}" >&2
    exit 3
  }
done
if [[ -e "${SCREEN_DIR}" || -e "${STRICT_OUTPUT}" ]]; then
  echo "ERROR: post-training evidence output already exists" >&2
  exit 4
fi

while kill -0 "${TRAIN_PID}" 2>/dev/null; do
  sleep 30
done
if ! grep -q "End of training" "${TRAIN_LOG}"; then
  echo "ERROR: training ended without the completion marker" >&2
  exit 5
fi
test -f "${CHECKPOINT}/adapter_model.safetensors" || {
  echo "ERROR: completed training did not produce the requested checkpoint" >&2
  exit 6
}

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export TOKENIZERS_PARALLELISM=false
cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
mkdir -p "${SCREEN_DIR}"

audit_args=()
if [[ "${REQUIRE_DIRECT_ACTION_HEAD}" == "1" ]]; then
  test -n "${EXPECTED_DIRECT_ACTION_HEAD_MSE_WEIGHT}" || {
    echo "ERROR: direct action head requires its frozen MSE weight" >&2
    exit 7
  }
  audit_args+=(
    --require-direct-action-head
    --expected-direct-action-head-mse-weight "${EXPECTED_DIRECT_ACTION_HEAD_MSE_WEIGHT}"
  )
fi
if [[ -n "${EXPECTED_DIRECT_ACTION_TARGET_PROTOCOL}" ]]; then
  audit_args+=(
    --expected-direct-action-target-protocol "${EXPECTED_DIRECT_ACTION_TARGET_PROTOCOL}"
  )
fi
if [[ -n "${EXPECTED_ACTION_LOSS_WEIGHTS}" ]]; then
  audit_args+=(--expected-action-loss-weights "${EXPECTED_ACTION_LOSS_WEIGHTS}")
fi
python scripts/audit_mobile_pi05_checkpoint.py \
  "${CHECKPOINT}" \
  --require-contract \
  --require-state-token \
  --require-mode-head \
  --require-full-action-projections \
  --expected-lora-rank 16 \
  --expected-lora-alpha 32 \
  --expected-mode-head-cross-entropy-weight "${EXPECTED_MODE_HEAD_CE_WEIGHT}" \
  --expected-optimizer-lr 0.00025 \
  "${audit_args[@]}" \
  --output "${SCREEN_DIR}/checkpoint-audit.json"

screen_status=0
env \
  MOBILE_PI05_EXPECTED_LORA_RANK=16 \
  MOBILE_PI05_EXPECTED_LORA_ALPHA=32 \
  MOBILE_PI05_EXPECTED_MODE_HEAD_CE_WEIGHT="${EXPECTED_MODE_HEAD_CE_WEIGHT}" \
  MOBILE_PI05_EXPECTED_DIRECT_ACTION_TARGET_PROTOCOL="${EXPECTED_DIRECT_ACTION_TARGET_PROTOCOL}" \
  MOBILE_PI05_EXPECTED_ACTION_LOSS_WEIGHTS="${EXPECTED_ACTION_LOSS_WEIGHTS}" \
  MOBILE_PI05_EXPECTED_OPTIMIZER_LR=0.00025 \
  bash scripts/screen_mobile_pi05_checkpoints_rocm.sh \
    "${RUN_ROOT}" \
    "${PANEL_DATASET_ROOT}" \
    "${STAGE_PANEL}" \
    "${ACTION_THRESHOLDS}" \
    "${SCREEN_DIR}" \
    mvp-competition-v3 \
    "${STEP}" || screen_status=$?

if [[ "${screen_status}" -ne 0 ]]; then
  "${PYTHON}" - "${EVIDENCE_DIR}/gate-decision.json" "${screen_status}" <<'PY'
import json
from pathlib import Path
import sys

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "schema_version": 1,
            "protocol": "pi05-mvp-competition-v3-gate-v1",
            "decision": "stop_before_closed_loop",
            "offline_screen_exit_code": int(sys.argv[2]),
            "pure_vla_closed_loop_started": False,
            "expert_reference_count": 0,
            "expert_fallback_count": 0,
            "claim_boundary": "Offline failure is not a closed-loop success result.",
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
  exit "${screen_status}"
fi

mkdir -p "${STRICT_OUTPUT}"
printf '%q ' \
  "${PYTHON}" "${ROOT_DIR}/scripts/run_with_rocm_telemetry.py" \
  --output "${STRICT_OUTPUT}/telemetry" --interval-seconds 1 -- \
  "${PYTHON}" "${ROOT_DIR}/scripts/collect_mobile_suction_dataset_rocm.py" \
  --config "${STRICT_DESIGN}" --output "${STRICT_OUTPUT}/rollouts" \
  --backend rocm --audit-only --wrist-rgbd --max-episodes 3 \
  --smolvla-checkpoint "${CHECKPOINT}" --policy-mode pi05_incremental \
  --policy-hz 3 --pi05-chunk-execution-protocol first-action-hold-v1 \
  --pi05-chunk-execution-steps 1 --require-vla-goal-verdict \
  --require-vla-grasp-mode --task-routing-authority vla_policy --workers 1 \
  --record-media-all-episodes \
  > "${STRICT_OUTPUT}/exact-command.sh"
printf '\n' >> "${STRICT_OUTPUT}/exact-command.sh"
chmod 0755 "${STRICT_OUTPUT}/exact-command.sh"
sha256sum "${STRICT_OUTPUT}/exact-command.sh" > "${STRICT_OUTPUT}/exact-command.sha256"

"${PYTHON}" "${ROOT_DIR}/scripts/run_with_rocm_telemetry.py" \
  --output "${STRICT_OUTPUT}/telemetry" \
  --interval-seconds 1 \
  -- \
  "${PYTHON}" "${ROOT_DIR}/scripts/collect_mobile_suction_dataset_rocm.py" \
    --config "${STRICT_DESIGN}" \
    --output "${STRICT_OUTPUT}/rollouts" \
    --backend rocm \
    --audit-only \
    --wrist-rgbd \
    --max-episodes 3 \
    --smolvla-checkpoint "${CHECKPOINT}" \
    --policy-mode pi05_incremental \
    --policy-hz 3 \
    --pi05-chunk-execution-protocol first-action-hold-v1 \
    --pi05-chunk-execution-steps 1 \
    --require-vla-goal-verdict \
    --require-vla-grasp-mode \
    --task-routing-authority vla_policy \
    --record-media-all-episodes \
    --workers 1

"${PYTHON}" scripts/summarize_mobile_vla_campaign.py \
  --collection-summary "${STRICT_OUTPUT}/rollouts/collection-summary.json" \
  --output "${STRICT_OUTPUT}/campaign-audit.json"

"${PYTHON}" - \
  "${EVIDENCE_DIR}/gate-decision.json" \
  "${STRICT_OUTPUT}/campaign-audit.json" <<'PY'
import json
from pathlib import Path
import sys

audit_path = Path(sys.argv[2])
audit = json.loads(audit_path.read_text(encoding="utf-8"))
payload = {
    "schema_version": 1,
    "protocol": "pi05-mvp-competition-v3-gate-v1",
    "decision": "strict_pure_vla3_completed",
    "offline_screen_exit_code": 0,
    "pure_vla_closed_loop_started": True,
    "campaign_audit": str(audit_path),
    "campaign_status": audit.get("status"),
    "metrics": audit.get("metrics", {}),
    "expert_reference_count": audit.get("expert_reference_count", 0),
    "expert_fallback_count": audit.get("expert_fallback_count", 0),
    "claim_boundary": "Competition development smoke only; report the exact pure-VLA numerator and denominator from campaign-audit.json.",
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
