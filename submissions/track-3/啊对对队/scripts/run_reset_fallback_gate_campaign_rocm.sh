#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${ROOT_DIR}/configs/catalog_v2.toml}"
CAMPAIGN_PATH="${2:-${ROOT_DIR}/configs/campaign_reset_fallback_gate_validation_v1.toml}"
OUTPUT_ROOT="${3:-${ROOT_DIR}/outputs/radeon-reset-fallback-gate-validation-v1}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh
python scripts/validate_campaign.py "${CAMPAIGN_PATH}"

if [[ -e "${OUTPUT_ROOT}" ]]; then
  echo "ERROR: output root already exists; choose a new path: ${OUTPUT_ROOT}" >&2
  exit 2
fi
mkdir -p "${OUTPUT_ROOT}"
cp "${CAMPAIGN_PATH}" "${OUTPUT_ROOT}/campaign.toml"

mapfile -t PROFILES < <(
  python - "${CAMPAIGN_PATH}" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    campaign = tomllib.load(handle)
for profile_id in campaign["evaluation"]["profile_ids"]:
    print(profile_id)
PY
)
readarray -t EVALUATION_VALUES < <(
  python - "${CAMPAIGN_PATH}" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    evaluation = tomllib.load(handle)["evaluation"]
local_ids = evaluation["local_episode_ids"]
if local_ids != list(range(local_ids[0], local_ids[0] + len(local_ids))):
    raise SystemExit("campaign runner requires a contiguous local episode range")
print(len(local_ids))
print(local_ids[0])
PY
)
EPISODES_PER_PROFILE="${EVALUATION_VALUES[0]}"
START_LOCAL_EPISODE="${EVALUATION_VALUES[1]}"
PROFILE_ARGS=()
for profile_id in "${PROFILES[@]}"; do
  PROFILE_ARGS+=(--profile "${profile_id}")
done

verify_summary() {
  local summary_path="$1"
  python - "${summary_path}" "${CAMPAIGN_PATH}" <<'PY'
import json
from pathlib import Path
import sys
import tomllib

summary_path = Path(sys.argv[1])
if not summary_path.is_file():
    raise SystemExit(f"summary is missing: {summary_path}")
payload = json.loads(summary_path.read_text(encoding="utf-8"))
with open(sys.argv[2], "rb") as handle:
    evaluation = tomllib.load(handle)["evaluation"]
episodes = payload.get("episodes", [])
if sorted(int(item["episode_index"]) for item in episodes) != sorted(evaluation["episode_ids"]):
    raise SystemExit("summary does not contain the frozen campaign episode set")
if {item.get("sample", {}).get("profile_id") for item in episodes} != set(evaluation["profile_ids"]):
    raise SystemExit("summary does not contain the frozen campaign profiles")
PY
}

run_group() {
  local run_id="$1"
  shift
  local run_root="${OUTPUT_ROOT}/${run_id}"
  local status=0
  python scripts/run_expert.py \
    --config "${CONFIG_PATH}" --backend rocm \
    --episodes "${EPISODES_PER_PROFILE}" \
    --start-episode "${START_LOCAL_EPISODE}" \
    "${PROFILE_ARGS[@]}" --output "${run_root}" "$@" \
    > "${OUTPUT_ROOT}/${run_id}.log" 2>&1 || status=$?
  verify_summary "${run_root}/expert/summary.json"
  if (( status == 139 )); then
    echo "WARN: Genesis exited with status 139 after writing a complete summary" >&2
    return 0
  fi
  return "${status}"
}

run_group collision-checked-reset --collision-checked-reset
run_group reset-risk-gated-planner \
  --collision-checked-reset \
  --geometry-aware-grasp-planning \
  --grasp-planning-reset-fallback-gate

python scripts/compare_expert_runs.py \
  --baseline "${OUTPUT_ROOT}/collision-checked-reset/expert/summary.json" \
  --candidate "${OUTPUT_ROOT}/reset-risk-gated-planner/expert/summary.json" \
  --allowed-config-difference task.geometry_aware_grasp_planning_enabled \
  --allowed-config-difference task.grasp_planning_reset_fallback_gate_enabled \
  --output "${OUTPUT_ROOT}/reset-vs-gated-planner.json"
python scripts/analyze_campaign_results.py \
  --run "collision-checked-reset=${OUTPUT_ROOT}/collision-checked-reset/expert/summary.json" \
  --run "reset-risk-gated-planner=${OUTPUT_ROOT}/reset-risk-gated-planner/expert/summary.json" \
  --reference collision-checked-reset \
  --output "${OUTPUT_ROOT}/paper-evaluation.json"
python scripts/audit_reset_fallback_gate.py \
  --baseline "${OUTPUT_ROOT}/collision-checked-reset/expert/summary.json" \
  --candidate "${OUTPUT_ROOT}/reset-risk-gated-planner/expert/summary.json" \
  --output "${OUTPUT_ROOT}/gate-attribution-audit.json"

for run_id in collision-checked-reset reset-risk-gated-planner; do
  python scripts/analyze_expert_failures.py \
    --summary "${OUTPUT_ROOT}/${run_id}/expert/summary.json" \
    --output "${OUTPUT_ROOT}/${run_id}-failure-analysis.json" --overwrite
  python scripts/compact_expert_summary.py \
    --summary "${OUTPUT_ROOT}/${run_id}/expert/summary.json" \
    --output "${OUTPUT_ROOT}/${run_id}-summary.json" --overwrite
done

sha256sum \
  "${OUTPUT_ROOT}"/*-summary.json \
  "${OUTPUT_ROOT}"/*-failure-analysis.json \
  "${OUTPUT_ROOT}"/*.log \
  "${OUTPUT_ROOT}"/reset-vs-gated-planner.json \
  "${OUTPUT_ROOT}"/paper-evaluation.json \
  "${OUTPUT_ROOT}"/gate-attribution-audit.json \
  "${OUTPUT_ROOT}"/campaign.toml > "${OUTPUT_ROOT}/COMPACT-SHA256SUMS"

echo "Reset-fallback gate campaign completed: ${OUTPUT_ROOT}"
