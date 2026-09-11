#!/usr/bin/env bash
# Preserve V18 action/progress heads, specialize only learned routing/tool heads,
# then fail closed through offline, strict pure-VLA, video, and delivery gates.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_CHECKPOINT="${1:?usage: $0 SOURCE_CHECKPOINT COLLECTION_ROOT EVIDENCE_ROOT RUN_ROOT DELIVERY_ROOT}"
COLLECTION_ROOT="${2:?usage: $0 SOURCE_CHECKPOINT COLLECTION_ROOT EVIDENCE_ROOT RUN_ROOT DELIVERY_ROOT}"
EVIDENCE_ROOT="${3:?usage: $0 SOURCE_CHECKPOINT COLLECTION_ROOT EVIDENCE_ROOT RUN_ROOT DELIVERY_ROOT}"
RUN_ROOT="${4:?usage: $0 SOURCE_CHECKPOINT COLLECTION_ROOT EVIDENCE_ROOT RUN_ROOT DELIVERY_ROOT}"
DELIVERY_ROOT="${5:?usage: $0 SOURCE_CHECKPOINT COLLECTION_ROOT EVIDENCE_ROOT RUN_ROOT DELIVERY_ROOT}"
PYTHON="/workspace/rdna/bin/python"
PREREGISTRATION="${ROOT_DIR}/configs/mobile_pi05_competition_v20_mode_only_preregistration.json"
SOURCE_SMOKE="${ROOT_DIR}/configs/mobile_pi05_single_box_v14_v7_strict_smoke_3.json"
DEPLOYMENT_PREREGISTRATION="${ROOT_DIR}/configs/mobile_pi05_competition_v18_deployment_progress_preregistration.json"
COLLECTOR_CONFIG="${EVIDENCE_ROOT}/collector-config.json"
COLLECTION_SUMMARY="${COLLECTION_ROOT}/collection-summary.json"
EXPERT_DATASET="${COLLECTION_ROOT}/lerobot_dataset"
DATASET_AUDIT="${EVIDENCE_ROOT}/mobile-dataset-audit.json"
ADMISSION_AUDIT="${EVIDENCE_ROOT}/admission-audit.json"
ABSOLUTE_DATASET="${COLLECTION_ROOT}/pi05-absolute-v20"
INCREMENTAL_DATASET="${COLLECTION_ROOT}/pi05-incremental-deployment-v2-v20"
SAMPLING_MANIFEST="${EVIDENCE_ROOT}/competition-sampling-manifest.json"
PANEL_DATASET="/workspace/persistence/parcel-sorter-opt-v1/runs/parcel-pi05-single-box-v14-mvp-incremental-deployment-v2-20260803"
PANEL="/workspace/persistence/parcel-sorter-opt-v1/evidence/pi05_vla/full_source_candidate_restart2_20260804/full_source_training_stage_panel.json"
CHECKPOINT="${RUN_ROOT}/checkpoints/000400/pretrained_model"
CALIBRATION_LOG="${EVIDENCE_ROOT}/calibration.log"
POSTTRAIN="${EVIDENCE_ROOT}/posttrain"
ACTION_WEIGHTS="8,8,8,1,1,1,32,32,32,1,1,1,1,32,32,32,1,1,1,1,128"
TARGET_PROTOCOL="normalized_quantile_unclipped_first_action_v3"

for path in \
  "${SOURCE_CHECKPOINT}" "${PREREGISTRATION}" "${SOURCE_SMOKE}" \
  "${DEPLOYMENT_PREREGISTRATION}" "${COLLECTOR_CONFIG}" \
  "${COLLECTION_SUMMARY}" "${EXPERT_DATASET}" "${PANEL_DATASET}" "${PANEL}"; do
  test -e "${path}" || { echo "ERROR: required immutable input is missing: ${path}" >&2; exit 2; }
done
for path in \
  "${DATASET_AUDIT}" "${ADMISSION_AUDIT}" "${ABSOLUTE_DATASET}" \
  "${INCREMENTAL_DATASET}" "${SAMPLING_MANIFEST}" "${RUN_ROOT}" \
  "${POSTTRAIN}" "${DELIVERY_ROOT}" "${DELIVERY_ROOT}.tar.gz" \
  "${DELIVERY_ROOT}.tar.gz.sha256"; do
  test ! -e "${path}" || { echo "ERROR: immutable output already exists: ${path}" >&2; exit 3; }
done

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export TOKENIZERS_PARALLELISM=false
cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh

"${PYTHON}" scripts/audit_mobile_dataset.py \
  --dataset-root "${EXPERT_DATASET}" --output "${DATASET_AUDIT}" \
  --min-episodes 2 --policy-modality rgbd

"${PYTHON}" scripts/audit_mobile_pi05_competition_v19_teacher_specialization.py \
  --preregistration "${PREREGISTRATION}" --source-smoke "${SOURCE_SMOKE}" \
  --deployment-preregistration "${DEPLOYMENT_PREREGISTRATION}" \
  --collector-config "${COLLECTOR_CONFIG}" \
  --collection-summary "${COLLECTION_SUMMARY}" --dataset-audit "${DATASET_AUDIT}" \
  --output "${ADMISSION_AUDIT}"

"${PYTHON}" - "${ADMISSION_AUDIT}" <<'PY'
import json
from pathlib import Path
import sys
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "passed" or payload.get("training_admission_allowed") is not True:
    raise SystemExit("V20 mode-only teacher admission did not pass")
PY

"${PYTHON}" scripts/build_mobile_pi05_residual_dataset.py \
  --source "${EXPERT_DATASET}" --output "${ABSOLUTE_DATASET}" \
  --action-contract absolute_v1 --collection-summary "${COLLECTION_SUMMARY}" \
  > "${EVIDENCE_ROOT}/absolute-dataset-build.log" 2>&1
"${PYTHON}" scripts/build_mobile_pi05_incremental_dataset.py \
  "${ABSOLUTE_DATASET}" "${INCREMENTAL_DATASET}" --deployment-state-v2 \
  > "${EVIDENCE_ROOT}/incremental-dataset-build.log" 2>&1
"${PYTHON}" scripts/build_mobile_pi05_competition_sampling_manifest.py \
  --dataset-root "${INCREMENTAL_DATASET}" --output "${SAMPLING_MANIFEST}" \
  --seed 11 --samples-per-cell 6 --progress-bins 5 \
  > "${EVIDENCE_ROOT}/sampling-manifest.log" 2>&1

printf '%q ' \
  "${PYTHON}" scripts/calibrate_mobile_pi05_heads_rocm.py \
  "${SOURCE_CHECKPOINT}" "${INCREMENTAL_DATASET}" "${SAMPLING_MANIFEST}" \
  "${PANEL_DATASET}" "${PANEL}" "${CHECKPOINT}" \
  --samples-per-cell 6 --feature-batch-size 4 --head-batch-size 64 \
  --epochs 300 --panel-repeat 20 --action-weights "${ACTION_WEIGHTS}" \
  --learning-rate 2.5e-4 --seed 11 --calibration-scope mode_only \
  > "${EVIDENCE_ROOT}/exact_train_command.sh"
printf '\n' >> "${EVIDENCE_ROOT}/exact_train_command.sh"
chmod 0755 "${EVIDENCE_ROOT}/exact_train_command.sh"
sha256sum "${EVIDENCE_ROOT}/exact_train_command.sh" > "${EVIDENCE_ROOT}/exact_train_command.sha256"

"${PYTHON}" scripts/calibrate_mobile_pi05_heads_rocm.py \
  "${SOURCE_CHECKPOINT}" "${INCREMENTAL_DATASET}" "${SAMPLING_MANIFEST}" \
  "${PANEL_DATASET}" "${PANEL}" "${CHECKPOINT}" \
  --samples-per-cell 6 --feature-batch-size 4 --head-batch-size 64 \
  --epochs 300 --panel-repeat 20 --action-weights "${ACTION_WEIGHTS}" \
  --learning-rate 2.5e-4 --seed 11 --calibration-scope mode_only \
  > "${CALIBRATION_LOG}" 2>&1

test -f "${CHECKPOINT}/adapter_model.safetensors" || { echo "ERROR: calibration checkpoint missing" >&2; exit 4; }
test -f "${CHECKPOINT}/PI05_TRAINING_CONTRACT.json" || { echo "ERROR: training contract missing" >&2; exit 5; }
echo "End of training" >> "${CALIBRATION_LOG}"
sha256sum \
  "${CHECKPOINT}/adapter_model.safetensors" \
  "${CHECKPOINT}/PI05_TRAINING_CONTRACT.json" \
  "${ABSOLUTE_DATASET}/PI05_ABSOLUTE_DATASET_MANIFEST.json" \
  "${INCREMENTAL_DATASET}/PI05_INCREMENTAL_DATASET_MANIFEST.json" \
  "${SAMPLING_MANIFEST}" > "${EVIDENCE_ROOT}/v20-artifact-hashes.sha256"

MOBILE_PI05_REQUIRE_DIRECT_ACTION_HEAD=1 \
MOBILE_PI05_EXPECTED_DIRECT_ACTION_HEAD_MSE_WEIGHT=4.0 \
MOBILE_PI05_EXPECTED_MODE_HEAD_CE_WEIGHT=12.0 \
MOBILE_PI05_EXPECTED_DIRECT_ACTION_TARGET_PROTOCOL="${TARGET_PROTOCOL}" \
MOBILE_PI05_EXPECTED_ACTION_LOSS_WEIGHTS="${ACTION_WEIGHTS}" \
  bash scripts/run_mvp_competition_v3_posttrain_rocm.sh \
    99999999 "${CALIBRATION_LOG}" "${RUN_ROOT}" "${POSTTRAIN}" 400

"${PYTHON}" scripts/build_competition_mvp_delivery.py \
  --checkpoint "${CHECKPOINT}" --posttrain-evidence "${POSTTRAIN}" \
  --preflight-evidence "${EVIDENCE_ROOT}" \
  --training-command "${EVIDENCE_ROOT}/exact_train_command.sh" \
  --code-root "${ROOT_DIR}" --output "${DELIVERY_ROOT}" --min-successes 2
"${PYTHON}" "${DELIVERY_ROOT}/VERIFY_DELIVERY.py" \
  > "${EVIDENCE_ROOT}/delivery-verify.stdout"
