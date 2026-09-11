#!/usr/bin/env bash
# Select B3-SW with its frozen paired gate, then run strict pure-VLA development.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POST_PID="${1:?usage: $0 POST_PID SCREEN_ROOT STRICT_OUTPUT [RUN_NAME RUN_ID]}"
SCREEN_ROOT="${2:?usage: $0 POST_PID SCREEN_ROOT STRICT_OUTPUT [RUN_NAME RUN_ID]}"
STRICT_OUTPUT="${3:?usage: $0 POST_PID SCREEN_ROOT STRICT_OUTPUT [RUN_NAME RUN_ID]}"
RUN_NAME="${4:-pi05-b3-sw-stage-weighted}"
RUN_ID="${5:-b3-sw}"
CONFIG="${ROOT_DIR}/configs/mobile_pi05_b3_sw_stage_weighted_flow_v1.json"
CONTROL_SCREEN="${ROOT_DIR}/outputs/pi05-b2-droid-full-action-projection-common-seed-v2/pi05-b2-droid-full-action-projection-step12000-six-observation-screen.json"
SELECTION="${SCREEN_ROOT}/B3_SW_PAIRED_ACTION_FIDELITY_SELECTION.json"

if [[ ! "${POST_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: POST_PID must be a positive integer" >&2
  exit 2
fi
if [[ -e "${SELECTION}" || -e "${STRICT_OUTPUT}" ]]; then
  echo "ERROR: B3-SW selection or strict-development output already exists" >&2
  exit 3
fi

while kill -0 "${POST_PID}" 2>/dev/null; do
  sleep 60
done

test -f "${CONFIG}" || {
  echo "ERROR: missing frozen B3-SW preregistration: ${CONFIG}" >&2
  exit 4
}
test -f "${CONTROL_SCREEN}" || {
  echo "ERROR: missing frozen B2 control screen: ${CONTROL_SCREEN}" >&2
  exit 4
}

candidate_args=()
for step in 3000 6000 9000 12000; do
  screen="${SCREEN_ROOT}/${RUN_NAME}-step${step}-six-observation-screen.json"
  if [[ ! -f "${screen}" ]]; then
    echo "ERROR: missing completed B3-SW screen: ${screen}" >&2
    exit 5
  fi
  diagnostic="${SCREEN_ROOT}/${RUN_NAME}-step${step}-high-noise-mode-probes.json"
  if [[ ! -f "${diagnostic}" ]]; then
    echo "ERROR: missing completed B3-SW high-noise diagnostic: ${diagnostic}" >&2
    exit 5
  fi
  candidate_args+=(--candidate "${screen}")
done

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
python "${ROOT_DIR}/scripts/compare_mobile_pi05_action_fidelity.py" \
  --control "${CONTROL_SCREEN}" \
  "${candidate_args[@]}" \
  --preregistered-config "${CONFIG}" \
  --expected-count 6 \
  --output "${SELECTION}" \
  --require-promotion

checkpoint="$(python - "${SELECTION}" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
selected = [item for item in payload.get("comparisons", ()) if item.get("selected")]
if payload.get("status") != "promoted" or len(selected) != 1:
    raise SystemExit("B3-SW selection is not uniquely promoted")
print(selected[0]["checkpoint"])
PY
)"

bash "${ROOT_DIR}/scripts/run_mobile_pi05_b0_strict_dev_rocm.sh" \
  "${checkpoint}" "${STRICT_OUTPUT}" "${RUN_ID}"

printf '{"status":"complete","selection":"%s","checkpoint":"%s","strict_output":"%s","automatic_confirmation":false}\n' \
  "${SELECTION}" "${checkpoint}" "${STRICT_OUTPUT}"
