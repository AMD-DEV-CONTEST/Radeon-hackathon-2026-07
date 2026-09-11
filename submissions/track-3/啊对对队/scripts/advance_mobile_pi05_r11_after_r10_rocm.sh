#!/usr/bin/env bash
# Advance from the fused-head R10 ablation to R11 with one observable state token.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
R9_R10_PID="${1:?usage: $0 R9_R10_PID R9_R10_ORCH R10_EVAL DATASET R11_RUN R11_LOG R11_EVAL ORCH_DIR}"
R9_R10_ORCH="${2:?usage: $0 R9_R10_PID R9_R10_ORCH R10_EVAL DATASET R11_RUN R11_LOG R11_EVAL ORCH_DIR}"
R10_EVAL="${3:?usage: $0 R9_R10_PID R9_R10_ORCH R10_EVAL DATASET R11_RUN R11_LOG R11_EVAL ORCH_DIR}"
DATASET_ROOT="${4:?usage: $0 R9_R10_PID R9_R10_ORCH R10_EVAL DATASET R11_RUN R11_LOG R11_EVAL ORCH_DIR}"
R11_RUN="${5:?usage: $0 R9_R10_PID R9_R10_ORCH R10_EVAL DATASET R11_RUN R11_LOG R11_EVAL ORCH_DIR}"
R11_LOG="${6:?usage: $0 R9_R10_PID R9_R10_ORCH R10_EVAL DATASET R11_RUN R11_LOG R11_EVAL ORCH_DIR}"
R11_EVAL="${7:?usage: $0 R9_R10_PID R9_R10_ORCH R10_EVAL DATASET R11_RUN R11_LOG R11_EVAL ORCH_DIR}"
ORCH_DIR="${8:?usage: $0 R9_R10_PID R9_R10_ORCH R10_EVAL DATASET R11_RUN R11_LOG R11_EVAL ORCH_DIR}"

if [[ ! "${R9_R10_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: R9-to-R10 process ID must be a positive integer" >&2
  exit 2
fi
for path in "${R11_RUN}" "${R11_LOG}" "${R11_LOG}.pid" "${R11_EVAL}" "${ORCH_DIR}"; do
  if [[ -e "${path}" ]]; then
    echo "ERROR: output already exists: ${path}" >&2
    exit 3
  fi
done

mkdir -p "${ORCH_DIR}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export TOKENIZERS_PARALLELISM=false
cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh >/dev/null

while kill -0 "${R9_R10_PID}" 2>/dev/null; do
  sleep 60
done
if [[ ! -f "${R9_R10_ORCH}/DECISION.json" ]]; then
  echo "ERROR: R9-to-R10 gate exited without a decision" >&2
  exit 4
fi

r10_decision="$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["decision"])' "${R9_R10_ORCH}/DECISION.json")"
if [[ "${r10_decision}" != "launch_r10_fused_mode_head" ]]; then
  python - "${ORCH_DIR}/DECISION.json" "${r10_decision}" <<'PY'
import json
from pathlib import Path
import sys

payload = {
    "schema_version": 1,
    "protocol": "pi05-r10-to-r11-gate-v1",
    "decision": "stop_before_r11",
    "upstream_decision": sys.argv[2],
    "r11_launched": False,
    "claim_boundary": "R11 is not launched when R9 already requires strict development closed-loop evaluation.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  exit 0
fi

readarray -t r10_pids < <(python - "${R9_R10_ORCH}/DECISION.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(int(payload["r10_launch"]["pid"]))
print(int(payload["r10_postscreen_pid"]))
PY
)
for pid in "${r10_pids[@]}"; do
  while kill -0 "${pid}" 2>/dev/null; do
    sleep 60
  done
done

decision="$(python - "${R10_EVAL}" <<'PY'
import glob
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
paths = sorted(glob.glob(str(root / "*-six-observation-screen.json")))
if len(paths) != 4:
    raise SystemExit(f"expected four R10 screens, found {len(paths)}")
payloads = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
passed = [item["checkpoint"] for item in payloads if item.get("status") == "passed"]
print(json.dumps({"screen_count": len(payloads), "passed_checkpoints": passed}))
PY
)"
printf '%s\n' "${decision}"

passed_count="$(python -c 'import json,sys; print(len(json.loads(sys.argv[1])["passed_checkpoints"]))' "${decision}")"
if [[ "${passed_count}" -gt 0 ]]; then
  python - "${ORCH_DIR}/DECISION.json" "${decision}" <<'PY'
import json
from pathlib import Path
import sys

payload = {
    "schema_version": 1,
    "protocol": "pi05-r10-to-r11-gate-v1",
    "decision": "run_r10_strict_development_closed_loop",
    "r10_screen": json.loads(sys.argv[2]),
    "r11_launched": False,
    "claim_boundary": "A training-distribution routing screen is not held-out generalization or closed-loop success.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  exit 0
fi

launch_json="$(env \
  MOBILE_PI05_MODE_LOSS_WEIGHT=1 \
  MOBILE_PI05_MODE_CE_WEIGHT=0 \
  MOBILE_PI05_STATE_TOKEN=1 \
  MOBILE_PI05_MODE_HEAD=1 \
  MOBILE_PI05_MODE_HEAD_CE_WEIGHT=2 \
  MOBILE_PI05_MODE_HEAD_CLASS_WEIGHTS=0.7608864696734059,0.920075223319229,1.6697952218430034 \
  MOBILE_PI05_LORA_R=16 \
  MOBILE_PI05_LORA_ALPHA=32 \
  MOBILE_PI05_SAVE_FREQ=3000 \
  bash scripts/launch_mobile_pi05_training_rocm.sh \
    "${DATASET_ROOT}" "${R11_RUN}" "${R11_LOG}" 12000)"
printf '%s\n' "${launch_json}"
r11_pid="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["pid"])' "${launch_json}")"

screen_log="${ORCH_DIR}/r11-postscreen.log"
nohup bash scripts/postscreen_mobile_pi05_training_rocm.sh \
  "${r11_pid}" "${R11_LOG}" "${R11_RUN}" "${DATASET_ROOT}" \
  "${R11_EVAL}" "pi05-r11-fused-head-state-token" 3000 6000 9000 12000 \
  >"${screen_log}" 2>&1 </dev/null &
r11_screen_pid=$!
printf '%s\n' "${r11_screen_pid}" >"${screen_log}.pid"

python - "${ORCH_DIR}/DECISION.json" "${decision}" "${launch_json}" "${r11_screen_pid}" <<'PY'
import json
from pathlib import Path
import sys

payload = {
    "schema_version": 1,
    "protocol": "pi05-r10-to-r11-gate-v1",
    "decision": "launch_r11_state_token",
    "r10_screen": json.loads(sys.argv[2]),
    "r11_launch": json.loads(sys.argv[3]),
    "r11_postscreen_pid": int(sys.argv[4]),
    "r11_state_token_enabled": True,
    "r11_fused_mode_head_enabled": True,
    "r11_lora_rank": 16,
    "expert_fallback_allowed": False,
    "claim_boundary": "R11 launch is not routing, held-out generalization, or closed-loop capability evidence.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
