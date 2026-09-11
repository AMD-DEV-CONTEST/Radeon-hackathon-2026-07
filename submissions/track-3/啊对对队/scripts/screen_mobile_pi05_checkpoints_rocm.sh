#!/usr/bin/env bash
# Run the hidden-input three-mode screen for one or more PI0.5 checkpoints.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USAGE="usage: $0 RUN_ROOT DATASET_ROOT STAGE_PANEL ACTION_THRESHOLDS OUTPUT_DIR RUN_NAME [STEP ...]"
RUN_ROOT="${1:?${USAGE}}"
DATASET_ROOT="${2:?${USAGE}}"
STAGE_PANEL="${3:?${USAGE}}"
ACTION_THRESHOLDS="${4:?${USAGE}}"
OUTPUT_DIR="${5:?${USAGE}}"
RUN_NAME="${6:?${USAGE}}"
shift 6
if [[ "$#" -eq 0 ]]; then
  STEPS=(1000 2000 3000)
else
  STEPS=("$@")
fi

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export TOKENIZERS_PARALLELISM=false
EXPECTED_STAGE_LOSS_WEIGHTS="${MOBILE_PI05_EXPECTED_STAGE_LOSS_WEIGHTS:-}"
EXPECTED_MODE_FLOW_LOSS_WEIGHTS="${MOBILE_PI05_EXPECTED_MODE_FLOW_LOSS_WEIGHTS:-}"
EXPECTED_MODE_FLOW_LOSS_NORMALIZER="${MOBILE_PI05_EXPECTED_MODE_FLOW_LOSS_NORMALIZER:-}"
test -f "${STAGE_PANEL}" || { echo "ERROR: missing frozen stage panel: ${STAGE_PANEL}" >&2; exit 2; }
test -f "${ACTION_THRESHOLDS}" || { echo "ERROR: missing action thresholds: ${ACTION_THRESHOLDS}" >&2; exit 2; }

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
mkdir -p "${OUTPUT_DIR}"

status=0
for step in "${STEPS[@]}"; do
  printf -v checkpoint_step "%06d" "${step}"
  checkpoint="${RUN_ROOT}/checkpoints/${checkpoint_step}/pretrained_model"
  probe="${OUTPUT_DIR}/${RUN_NAME}-step${step}-stage-panel-probes.json"
  screen="${OUTPUT_DIR}/${RUN_NAME}-step${step}-stage-panel-screen.json"
  audit="${OUTPUT_DIR}/${RUN_NAME}-step${step}-checkpoint-audit.json"
  log="${OUTPUT_DIR}/${RUN_NAME}-step${step}-stage-panel-probes.log"

  if [[ ! -f "${checkpoint}/adapter_model.safetensors" ]]; then
    echo "ERROR: missing PI0.5 adapter: ${checkpoint}" >&2
    status=3
    continue
  fi

  audit_args=(--require-full-action-projections)
  if [[ -n "${EXPECTED_STAGE_LOSS_WEIGHTS}" ]]; then
    audit_args+=(--expected-stage-loss-weights "${EXPECTED_STAGE_LOSS_WEIGHTS}")
  fi
  if [[ -n "${EXPECTED_MODE_FLOW_LOSS_WEIGHTS}" ]]; then
    audit_args+=(
      --expected-mode-flow-loss-weights "${EXPECTED_MODE_FLOW_LOSS_WEIGHTS}"
      --expected-mode-flow-loss-population-normalizer "${EXPECTED_MODE_FLOW_LOSS_NORMALIZER}"
    )
  fi
  if ! python scripts/audit_mobile_pi05_checkpoint.py \
    "${checkpoint}" \
    --require-contract \
    "${audit_args[@]}" \
    --output "${audit}"; then
    echo "ERROR: PI0.5 checkpoint audit failed: ${checkpoint}" >&2
    status=4
    continue
  fi

  python scripts/probe_mobile_pi05_checkpoint_rocm.py \
    "${checkpoint}" \
    "${DATASET_ROOT}" \
    --panel "${STAGE_PANEL}" \
    --samples 3 \
    --output "${probe}" 2>&1 | tee "${log}"

  if ! python scripts/summarize_mobile_pi05_mode_screen.py \
    --probe "${probe}" \
    --design "${STAGE_PANEL}" \
    --thresholds "${ACTION_THRESHOLDS}" \
    --output "${screen}"; then
    status=2
  fi
done

exit "${status}"
