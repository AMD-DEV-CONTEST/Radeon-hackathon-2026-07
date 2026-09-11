#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${ROOT_DIR}/configs/catalog_v2.toml}"
OUTPUT_ROOT="${2:-${ROOT_DIR}/outputs/radeon-reset-ab-v1}"
EPISODES="${RESET_AB_EPISODES:-20}"
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
  echo "ERROR: the audited reset-pose protocol requires exactly 20 episodes" >&2
  exit 4
fi

BASELINE_ROOT="${OUTPUT_ROOT}/baseline"
CANDIDATE_ROOT="${OUTPUT_ROOT}/candidate-c"
CANDIDATE_QPOS=(-1.0124 1.0 1.4 -1.6878 -1.5799 1.7757 1.4602 0.04 0.04)

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
  --output "${BASELINE_ROOT}"

run_expert_checked "${CANDIDATE_ROOT}/expert/summary.json" \
  --config "${CONFIG_PATH}" \
  --backend rocm \
  --episodes "${EPISODES}" \
  --start-episode 0 \
  --profile "${PROFILE}" \
  --reset-qpos "${CANDIDATE_QPOS[@]}" \
  --output "${CANDIDATE_ROOT}"

python scripts/compare_expert_runs.py \
  --baseline "${BASELINE_ROOT}/expert/summary.json" \
  --candidate "${CANDIDATE_ROOT}/expert/summary.json" \
  --allowed-config-difference control.reset_qpos \
  --output "${OUTPUT_ROOT}/comparison.json"

sha256sum \
  "${BASELINE_ROOT}/expert/summary.json" \
  "${CANDIDATE_ROOT}/expert/summary.json" \
  "${OUTPUT_ROOT}/comparison.json" > "${OUTPUT_ROOT}/SHA256SUMS"

echo "Reset-pose A/B completed: ${OUTPUT_ROOT}"
