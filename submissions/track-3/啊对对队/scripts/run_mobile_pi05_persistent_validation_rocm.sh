#!/usr/bin/env bash
# Measure a full-authority PI0.5 campaign including one persistent model load.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKPOINT="${1:?usage: $0 CHECKPOINT OUTPUT [DESIGN]}"
OUTPUT="${2:?usage: $0 CHECKPOINT OUTPUT [DESIGN]}"
DESIGN="${3:-${ROOT_DIR}/configs/mobile_pi05_development_validation_30_v1.json}"

if [[ -e "${OUTPUT}" ]]; then
  echo "ERROR: persistent validation output must be new: ${OUTPUT}" >&2
  exit 2
fi
mkdir -p "${OUTPUT}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

python "${ROOT_DIR}/scripts/run_with_rocm_telemetry.py" \
  --output "${OUTPUT}/telemetry" \
  --interval-seconds 1 \
  -- \
  bash "${ROOT_DIR}/scripts/run_mobile_pi05_persistent_campaign_inner_rocm.sh" \
    "${CHECKPOINT}" "${OUTPUT}" "${DESIGN}"

python "${ROOT_DIR}/scripts/summarize_mobile_pi05_validation.py" \
  --design "${DESIGN}" \
  --campaign-audit "${OUTPUT}/campaign-audit.json" \
  --telemetry-summary "${OUTPUT}/telemetry/rocm-telemetry-summary.json" \
  --output "${OUTPUT}/validation-summary.json"
