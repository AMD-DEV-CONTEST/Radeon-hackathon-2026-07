#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${ROOT_DIR}/configs/catalog_v2.toml}"
OUTPUT_ROOT="${2:-${ROOT_DIR}/outputs/radeon-approach-aabb-ab-v1}"
AABB_GUARD_DISTANCE_M="${AABB_GUARD_DISTANCE_M:-0.040}"
EPISODES="${APPROACH_AABB_AB_EPISODES:-20}"
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
if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "ERROR: config not found: ${CONFIG_PATH}" >&2
  exit 3
fi
if [[ "${EPISODES}" != "20" ]]; then
  echo "ERROR: the audited approach-AABB protocol requires exactly 20 episodes" >&2
  exit 4
fi

mkdir -p "${OUTPUT_ROOT}"
BASELINE_ROOT="${OUTPUT_ROOT}/baseline"
CANDIDATE_ROOT="${OUTPUT_ROOT}/candidate-precontact-aabb"

summary_is_complete() {
  local summary_path="$1"
  python - "${summary_path}" "${EPISODES}" "${PROFILE}" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
expected_episodes = int(sys.argv[2])
expected_profile = sys.argv[3]
if not path.is_file():
    raise SystemExit(f"summary is missing: {path}")
payload = json.loads(path.read_text(encoding="utf-8"))
episodes = payload.get("episodes", [])
indices = [int(episode["episode_index"]) for episode in episodes]
profiles = {episode.get("sample", {}).get("profile_id") for episode in episodes}
expected_indices = [7_000_000 + index for index in range(expected_episodes)]
if len(episodes) != expected_episodes or sorted(set(indices)) != expected_indices:
    raise SystemExit("summary does not contain the expected fixed episode namespace")
if payload.get("evaluation_range", {}).get("num_episodes") != expected_episodes:
    raise SystemExit("summary evaluation range is incomplete")
if profiles != {expected_profile}:
    raise SystemExit(f"summary profiles differ: {sorted(str(value) for value in profiles)}")
PY
}

run_checked() {
  local summary_path="$1"
  shift
  local status=0
  python scripts/run_expert.py "$@" || status=$?
  if summary_is_complete "${summary_path}"; then
    if (( status == 139 )); then
      echo "WARN: Genesis exited with status 139 after writing a complete summary" >&2
      return 0
    fi
    return "${status}"
  fi
  echo "ERROR: expert run did not satisfy its summary postcondition" >&2
  return "${status:-5}"
}

run_checked "${BASELINE_ROOT}/expert/summary.json" \
  --config "${CONFIG_PATH}" --backend rocm --episodes "${EPISODES}" \
  --start-episode 0 --profile "${PROFILE}" --output "${BASELINE_ROOT}" \
  > "${OUTPUT_ROOT}/baseline-run.log" 2>&1

run_checked "${CANDIDATE_ROOT}/expert/summary.json" \
  --config "${CONFIG_PATH}" --backend rocm --episodes "${EPISODES}" \
  --start-episode 0 --profile "${PROFILE}" \
  --precontact-aabb-guard-distance "${AABB_GUARD_DISTANCE_M}" \
  --output "${CANDIDATE_ROOT}" \
  > "${OUTPUT_ROOT}/candidate-run.log" 2>&1

python scripts/compare_expert_runs.py \
  --baseline "${BASELINE_ROOT}/expert/summary.json" \
  --candidate "${CANDIDATE_ROOT}/expert/summary.json" \
  --allowed-config-difference control.precontact_aabb_guard_distance_m \
  --output "${OUTPUT_ROOT}/comparison.json"

python scripts/analyze_expert_failures.py \
  --summary "${BASELINE_ROOT}/expert/summary.json" \
  --output "${OUTPUT_ROOT}/baseline_failure_analysis.json" --overwrite
python scripts/analyze_expert_failures.py \
  --summary "${CANDIDATE_ROOT}/expert/summary.json" \
  --output "${OUTPUT_ROOT}/candidate_failure_analysis.json" --overwrite

sha256sum \
  "${BASELINE_ROOT}/expert/summary.json" \
  "${CANDIDATE_ROOT}/expert/summary.json" \
  "${OUTPUT_ROOT}/comparison.json" \
  "${OUTPUT_ROOT}/baseline_failure_analysis.json" \
  "${OUTPUT_ROOT}/candidate_failure_analysis.json" \
  "${OUTPUT_ROOT}/baseline-run.log" \
  "${OUTPUT_ROOT}/candidate-run.log" > "${OUTPUT_ROOT}/SHA256SUMS"

echo "Approach-AABB A/B completed: ${OUTPUT_ROOT}"
