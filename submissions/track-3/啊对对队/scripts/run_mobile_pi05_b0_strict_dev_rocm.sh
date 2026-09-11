#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKPOINT="${1:?usage: $0 CHECKPOINT OUTPUT_DIR [RUN_ID]}"
OUTPUT_DIR="${2:?usage: $0 CHECKPOINT OUTPUT_DIR [RUN_ID]}"
RUN_ID="${3:-b0}"
CONFIG="${ROOT_DIR}/configs/mobile_pi05_b0_absolute_strict_dev_v1.json"

if [[ ! -f "${CHECKPOINT}/adapter_model.safetensors" ]]; then
  echo "ERROR: missing PI0.5 adapter: ${CHECKPOINT}" >&2
  exit 2
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
  echo "ERROR: strict-development output already exists: ${OUTPUT_DIR}" >&2
  exit 3
fi

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export TOKENIZERS_PARALLELISM=false
cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh

python scripts/collect_mobile_suction_dataset_rocm.py \
  --config "${CONFIG}" \
  --output "${OUTPUT_DIR}/campaign" \
  --backend rocm \
  --audit-only \
  --smolvla-checkpoint "${CHECKPOINT}" \
  --policy-mode pi05_absolute \
  --policy-hz 5 \
  --pi05-chunk-execution-protocol first-action-hold-v1 \
  --pi05-chunk-execution-steps 1 \
  --require-vla-goal-verdict \
  --require-vla-grasp-mode

python scripts/summarize_mobile_vla_campaign.py \
  --collection-summary "${OUTPUT_DIR}/campaign/collection-summary.json" \
  --output "${OUTPUT_DIR}/strict-vla-audit.json"

python - "${OUTPUT_DIR}/strict-vla-audit.json" "${RUN_ID}" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
run_id = sys.argv[2]
payload = json.loads(path.read_text(encoding="utf-8"))
runs = payload.get("runs", [])
passed = (
    payload.get("status") == "passed"
    and payload.get("trials") == 3
    and payload.get("successes") == 3
    and payload.get("vla_qualified_run_count") == 3
    and payload.get("pure_vla_complete_success_count") == 3
    and payload.get("expert_fallback_count") == 0
    and payload.get("force_violation_count") == 0
    and all(run.get("policy_authority") == "absolute_vla_action_candidate" for run in runs)
    and all(run.get("expert_reference_used") is False for run in runs)
)
gate = {
    "schema_version": 1,
    "protocol": f"pi05-{run_id}-absolute-strict-development-gate-v1",
    "status": "passed" if passed else "failed",
    "trials": payload.get("trials"),
    "successes": payload.get("successes"),
    "vla_qualified_run_count": payload.get("vla_qualified_run_count"),
    "pure_vla_complete_success_count": payload.get("pure_vla_complete_success_count"),
    "expert_fallback_count": payload.get("expert_fallback_count"),
    "force_violation_count": payload.get("force_violation_count"),
    "claim_boundary": "Development gate only; never part of the frozen 105-rollout result.",
}
gate_path = path.with_name("STRICT_GATE.json")
gate_path.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
print(json.dumps(gate, indent=2))
raise SystemExit(0 if passed else 2)
PY
