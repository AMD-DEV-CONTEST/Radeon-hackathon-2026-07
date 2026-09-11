#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${ROOT_DIR}/configs/catalog_v2.toml}"
OUTPUT_ROOT="${2:-${ROOT_DIR}/outputs/radeon-reset-fallback-gate-probes-v1}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh

if [[ -e "${OUTPUT_ROOT}" ]]; then
  echo "ERROR: output root already exists; choose a new path: ${OUTPUT_ROOT}" >&2
  exit 2
fi
mkdir -p "${OUTPUT_ROOT}"

run_probe() {
  local probe_id="$1"
  local profile_id="$2"
  local local_episode_id="$3"
  local expected_fallback="$4"
  local expected_active="$5"
  local run_root="${OUTPUT_ROOT}/${probe_id}"
  local status=0

  python scripts/run_expert.py \
    --config "${CONFIG_PATH}" --backend rocm \
    --profile "${profile_id}" --episodes 1 \
    --start-episode "${local_episode_id}" \
    --collision-checked-reset \
    --geometry-aware-grasp-planning \
    --grasp-planning-reset-fallback-gate \
    --output "${run_root}" > "${OUTPUT_ROOT}/${probe_id}.log" 2>&1 || status=$?

  python - "${run_root}/expert/summary.json" "${expected_fallback}" "${expected_active}" <<'PY'
import json
from pathlib import Path
import sys

summary_path = Path(sys.argv[1])
payload = json.loads(summary_path.read_text(encoding="utf-8"))
episodes = payload.get("episodes", [])
if len(episodes) != 1:
    raise SystemExit("probe must contain exactly one episode")
safety = episodes[0].get("safety_summary", {})
expected_fallback = sys.argv[2].lower() == "true"
expected_active = sys.argv[3].lower() == "true"
if safety.get("grasp_planning_reset_fallback_gate_enabled") is not True:
    raise SystemExit("reset-fallback planner gate telemetry is missing")
if bool(safety.get("collision_checked_reset_used")) != expected_fallback:
    raise SystemExit("collision-reset fallback result differs from the probe contract")
if bool(safety.get("geometry_aware_grasp_planning_active")) != expected_active:
    raise SystemExit("planner activation differs from the probe contract")
attempts = int(safety.get("grasp_plan_attempts", 0))
if expected_active and attempts < 1:
    raise SystemExit("active planner produced no planning attempt")
if not expected_active and attempts != 0:
    raise SystemExit("gated planner ran without measured reset risk")
result = episodes[0]["result"]
print(
    f"episode={episodes[0]['episode_index']} success={result['success']} "
    f"max_force_n={result['max_contact_force_n']:.3f} "
    f"fallback={expected_fallback} planner_active={expected_active} attempts={attempts}"
)
PY

  if (( status == 139 )); then
    echo "WARN: Genesis exited with status 139 after writing a complete probe" >&2
    return 0
  fi
  return "${status}"
}

run_probe medium-no-reset-risk medium_carton 100004 false false
run_probe narrow-carton-reset-risk large_narrow_carton 100002 true true
run_probe low-box-sentinel small_carton 100000 false false

sha256sum "${OUTPUT_ROOT}"/*/expert/summary.json "${OUTPUT_ROOT}"/*.log \
  > "${OUTPUT_ROOT}/SHA256SUMS"
echo "Reset-fallback gate probes completed: ${OUTPUT_ROOT}"
