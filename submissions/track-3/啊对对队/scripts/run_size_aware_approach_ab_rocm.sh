#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${ROOT_DIR}/configs/catalog_v2.toml}"
OUTPUT_ROOT="${2:-${ROOT_DIR}/outputs/radeon-size-aware-ab-v1}"
MARGIN_M="${SIZE_AWARE_APPROACH_MARGIN_M:-0.020}"
EPISODES="${SIZE_AWARE_AB_EPISODES:-20}"
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
  echo "ERROR: the audited size-aware protocol requires exactly 20 episodes" >&2
  exit 4
fi

mkdir -p "${OUTPUT_ROOT}"

BASELINE_ROOT="${OUTPUT_ROOT}/baseline"
CANDIDATE_ROOT="${OUTPUT_ROOT}/candidate-size-aware"

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
if len(episodes) != expected_episodes or len(set(indices)) != expected_episodes:
    raise SystemExit("summary does not contain the expected unique episodes")
if payload.get("evaluation_range", {}).get("num_episodes") != expected_episodes:
    raise SystemExit("summary evaluation range is incomplete")
if profiles != {expected_profile}:
    raise SystemExit(f"summary profiles differ: {sorted(str(value) for value in profiles)}")
PY
}

run_expert_checked() {
  local summary_path="$1"
  shift
  local status=0
  python scripts/run_expert.py "$@" || status=$?
  if summary_is_complete "${summary_path}"; then
    if (( status == 139 )); then
      echo "WARN: Genesis exited with status 139 after writing a complete summary; continuing" >&2
      return 0
    fi
    return "${status}"
  fi
  echo "ERROR: expert run did not satisfy its summary postcondition" >&2
  if (( status == 0 )); then
    return 5
  fi
  return "${status}"
}

run_expert_checked "${BASELINE_ROOT}/expert/summary.json" \
  --config "${CONFIG_PATH}" \
  --backend rocm \
  --episodes "${EPISODES}" \
  --start-episode 0 \
  --profile "${PROFILE}" \
  --output "${BASELINE_ROOT}" \
  > "${OUTPUT_ROOT}/baseline-run.log" 2>&1

run_expert_checked "${CANDIDATE_ROOT}/expert/summary.json" \
  --config "${CONFIG_PATH}" \
  --backend rocm \
  --episodes "${EPISODES}" \
  --start-episode 0 \
  --profile "${PROFILE}" \
  --size-aware-approach \
  --approach-clearance-margin "${MARGIN_M}" \
  --output "${CANDIDATE_ROOT}" \
  > "${OUTPUT_ROOT}/candidate-run.log" 2>&1

python scripts/compare_expert_runs.py \
  --baseline "${BASELINE_ROOT}/expert/summary.json" \
  --candidate "${CANDIDATE_ROOT}/expert/summary.json" \
  --allowed-config-difference task.approach_clearance_margin_m \
  --allowed-config-difference task.size_aware_approach_enabled \
  --output "${OUTPUT_ROOT}/comparison.json"

sha256sum \
  "${BASELINE_ROOT}/expert/summary.json" \
  "${CANDIDATE_ROOT}/expert/summary.json" \
  "${OUTPUT_ROOT}/comparison.json" \
  "${OUTPUT_ROOT}/baseline-run.log" \
  "${OUTPUT_ROOT}/candidate-run.log" > "${OUTPUT_ROOT}/SHA256SUMS"

echo "Size-aware approach A/B completed: ${OUTPUT_ROOT}"
