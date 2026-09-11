#!/usr/bin/env bash
# Run a strict absolute-PI0.5 frozen validation with Radeon energy telemetry.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKPOINT="${1:?usage: $0 CHECKPOINT OUTPUT [DESIGN]}"
OUTPUT="${2:?usage: $0 CHECKPOINT OUTPUT [DESIGN]}"
DESIGN="${3:-${ROOT_DIR}/configs/mobile_pi05_frozen_validation_60_v1.json}"

if [[ ! -f "${CHECKPOINT}/config.json" ]]; then
  echo "ERROR: checkpoint config is missing: ${CHECKPOINT}" >&2
  exit 2
fi
if [[ ! -f "${DESIGN}" ]]; then
  echo "ERROR: frozen design is missing: ${DESIGN}" >&2
  exit 3
fi
if [[ -e "${OUTPUT}" ]]; then
  echo "ERROR: frozen validation output must not already exist: ${OUTPUT}" >&2
  exit 4
fi

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
mkdir -p "${OUTPUT}"

python "${ROOT_DIR}/scripts/run_with_rocm_telemetry.py" \
  --output "${OUTPUT}/telemetry" \
  --interval-seconds 1 \
  -- \
  python "${ROOT_DIR}/scripts/collect_mobile_suction_dataset_rocm.py" \
    --config "${DESIGN}" \
    --output "${OUTPUT}/rollouts" \
    --backend rocm \
    --audit-only \
    --smolvla-checkpoint "${CHECKPOINT}" \
    --policy-mode pi05_absolute \
    --policy-hz 3 \
    --pi05-chunk-execution-protocol first-action-hold-v1 \
    --pi05-chunk-execution-steps 1 \
    --require-vla-goal-verdict \
    --require-vla-grasp-mode \
    --workers 1

python "${ROOT_DIR}/scripts/summarize_mobile_vla_campaign.py" \
  --collection-summary "${OUTPUT}/rollouts/collection-summary.json" \
  --output "${OUTPUT}/campaign-audit.json"

python "${ROOT_DIR}/scripts/summarize_mobile_pi05_validation.py" \
  --design "${DESIGN}" \
  --campaign-audit "${OUTPUT}/campaign-audit.json" \
  --telemetry-summary "${OUTPUT}/telemetry/rocm-telemetry-summary.json" \
  --output "${OUTPUT}/frozen-validation-summary.json"
