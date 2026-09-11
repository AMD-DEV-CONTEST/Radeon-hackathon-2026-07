#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${ROOT_DIR}/configs/catalog_v2.toml}"
OUTPUT_ROOT="${2:-${ROOT_DIR}/outputs/radeon-geometry-aware-grasp-planning-ab-v2-tiered}"
EPISODES="${GEOMETRY_GRASP_PLANNING_AB_EPISODES:-20}"
PROFILE="large_narrow_carton"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh

if [[ -e "${OUTPUT_ROOT}" ]]; then
  echo "ERROR: output root already exists; choose a new path: ${OUTPUT_ROOT}" >&2
  exit 2
fi
if [[ "${EPISODES}" != "20" ]]; then
  echo "ERROR: the audited grasp-planning protocol requires exactly 20 episodes" >&2
  exit 3
fi

mkdir -p "${OUTPUT_ROOT}"
BASELINE_ROOT="${OUTPUT_ROOT}/baseline-collision-checked-reset"
CANDIDATE_ROOT="${OUTPUT_ROOT}/candidate-geometry-aware-grasp-planning"

run_checked() {
  local summary_path="$1"
  shift
  local status=0
  python scripts/run_expert.py "$@" || status=$?
  python - "${summary_path}" "${EPISODES}" "${PROFILE}" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
expected = int(sys.argv[2])
profile = sys.argv[3]
if not path.is_file():
    raise SystemExit(f"summary is missing: {path}")
payload = json.loads(path.read_text(encoding="utf-8"))
episodes = payload.get("episodes", [])
indices = sorted({int(item["episode_index"]) for item in episodes})
if len(episodes) != expected or indices != list(range(7_000_000, 7_000_000 + expected)):
    raise SystemExit("summary does not contain the fixed episode namespace")
if {item.get("sample", {}).get("profile_id") for item in episodes} != {profile}:
    raise SystemExit("summary contains an unexpected profile")
PY
  if (( status == 139 )); then
    echo "WARN: Genesis exited with status 139 after writing a complete summary" >&2
    return 0
  fi
  return "${status}"
}

run_checked "${BASELINE_ROOT}/expert/summary.json" \
  --config "${CONFIG_PATH}" --backend rocm --episodes "${EPISODES}" \
  --start-episode 0 --profile "${PROFILE}" --collision-checked-reset \
  --output "${BASELINE_ROOT}" > "${OUTPUT_ROOT}/baseline-run.log" 2>&1

run_checked "${CANDIDATE_ROOT}/expert/summary.json" \
  --config "${CONFIG_PATH}" --backend rocm --episodes "${EPISODES}" \
  --start-episode 0 --profile "${PROFILE}" --collision-checked-reset \
  --geometry-aware-grasp-planning --output "${CANDIDATE_ROOT}" \
  > "${OUTPUT_ROOT}/candidate-run.log" 2>&1

python scripts/compare_expert_runs.py \
  --baseline "${BASELINE_ROOT}/expert/summary.json" \
  --candidate "${CANDIDATE_ROOT}/expert/summary.json" \
  --allowed-config-difference task.geometry_aware_grasp_planning_enabled \
  --output "${OUTPUT_ROOT}/comparison.json"

python scripts/analyze_expert_failures.py \
  --summary "${BASELINE_ROOT}/expert/summary.json" \
  --output "${OUTPUT_ROOT}/baseline_failure_analysis.json" --overwrite
python scripts/analyze_expert_failures.py \
  --summary "${CANDIDATE_ROOT}/expert/summary.json" \
  --output "${OUTPUT_ROOT}/candidate_failure_analysis.json" --overwrite

python scripts/compact_expert_summary.py \
  --summary "${BASELINE_ROOT}/expert/summary.json" \
  --output "${OUTPUT_ROOT}/baseline-summary.json" --overwrite
python scripts/compact_expert_summary.py \
  --summary "${CANDIDATE_ROOT}/expert/summary.json" \
  --output "${OUTPUT_ROOT}/candidate-summary.json" --overwrite

sha256sum \
  "${BASELINE_ROOT}/expert/summary.json" \
  "${CANDIDATE_ROOT}/expert/summary.json" \
  "${OUTPUT_ROOT}/comparison.json" \
  "${OUTPUT_ROOT}/baseline_failure_analysis.json" \
  "${OUTPUT_ROOT}/candidate_failure_analysis.json" \
  "${OUTPUT_ROOT}/baseline-run.log" \
  "${OUTPUT_ROOT}/candidate-run.log" > "${OUTPUT_ROOT}/SHA256SUMS"

sha256sum \
  "${OUTPUT_ROOT}/baseline-summary.json" \
  "${OUTPUT_ROOT}/candidate-summary.json" \
  "${OUTPUT_ROOT}/comparison.json" \
  "${OUTPUT_ROOT}/baseline_failure_analysis.json" \
  "${OUTPUT_ROOT}/candidate_failure_analysis.json" \
  "${OUTPUT_ROOT}/baseline-run.log" \
  "${OUTPUT_ROOT}/candidate-run.log" > "${OUTPUT_ROOT}/COMPACT-SHA256SUMS"

echo "Geometry-aware grasp-planning A/B completed: ${OUTPUT_ROOT}"
