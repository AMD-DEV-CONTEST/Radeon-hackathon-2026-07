#!/usr/bin/env bash
# Advance from R11 to the matched rank-32 R12 ablation without GPU overlap.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
R10_R11_PID="${1:?usage: $0 R10_R11_PID R10_R11_ORCH R11_EVAL DATASET R12_RUN R12_LOG R12_EVAL ORCH_DIR}"
R10_R11_ORCH="${2:?usage: $0 R10_R11_PID R10_R11_ORCH R11_EVAL DATASET R12_RUN R12_LOG R12_EVAL ORCH_DIR}"
R11_EVAL="${3:?usage: $0 R10_R11_PID R10_R11_ORCH R11_EVAL DATASET R12_RUN R12_LOG R12_EVAL ORCH_DIR}"
DATASET_ROOT="${4:?usage: $0 R10_R11_PID R10_R11_ORCH R11_EVAL DATASET R12_RUN R12_LOG R12_EVAL ORCH_DIR}"
R12_RUN="${5:?usage: $0 R10_R11_PID R10_R11_ORCH R11_EVAL DATASET R12_RUN R12_LOG R12_EVAL ORCH_DIR}"
R12_LOG="${6:?usage: $0 R10_R11_PID R10_R11_ORCH R11_EVAL DATASET R12_RUN R12_LOG R12_EVAL ORCH_DIR}"
R12_EVAL="${7:?usage: $0 R10_R11_PID R10_R11_ORCH R11_EVAL DATASET R12_RUN R12_LOG R12_EVAL ORCH_DIR}"
ORCH_DIR="${8:?usage: $0 R10_R11_PID R10_R11_ORCH R11_EVAL DATASET R12_RUN R12_LOG R12_EVAL ORCH_DIR}"

if [[ ! "${R10_R11_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: R10-to-R11 process ID must be a positive integer" >&2
  exit 2
fi
for path in "${R12_RUN}" "${R12_LOG}" "${R12_LOG}.pid" "${R12_EVAL}" "${ORCH_DIR}"; do
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

while kill -0 "${R10_R11_PID}" 2>/dev/null; do
  sleep 60
done
if [[ ! -f "${R10_R11_ORCH}/DECISION.json" ]]; then
  echo "ERROR: R10-to-R11 gate exited without a decision" >&2
  exit 4
fi

r11_decision="$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["decision"])' "${R10_R11_ORCH}/DECISION.json")"
if [[ "${r11_decision}" != "launch_r11_state_token" ]]; then
  python - "${ORCH_DIR}/DECISION.json" "${r11_decision}" <<'PY'
import json
from pathlib import Path
import sys

payload = {
    "schema_version": 1,
    "protocol": "pi05-r11-to-r12-gate-v1",
    "decision": "stop_before_r12",
    "upstream_decision": sys.argv[2],
    "r12_launched": False,
    "claim_boundary": "R12 is not launched when an upstream candidate already requires strict closed-loop evaluation.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  exit 0
fi

readarray -t r11_pids < <(python - "${R10_R11_ORCH}/DECISION.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(int(payload["r11_launch"]["pid"]))
print(int(payload["r11_postscreen_pid"]))
PY
)
r11_run="$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["r11_launch"]["output"])' "${R10_R11_ORCH}/DECISION.json")"
for pid in "${r11_pids[@]}"; do
  while kill -0 "${pid}" 2>/dev/null; do
    sleep 60
  done
done

decision="$(python - "${R11_EVAL}" <<'PY'
import glob
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
paths = sorted(glob.glob(str(root / "*-six-observation-screen.json")))
if len(paths) != 4:
    raise SystemExit(f"expected four R11 screens, found {len(paths)}")
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
    "protocol": "pi05-r11-to-r12-gate-v1",
    "decision": "run_r11_strict_development_closed_loop",
    "r11_screen": json.loads(sys.argv[2]),
    "r12_launched": False,
    "claim_boundary": "A training-distribution routing screen is not held-out generalization or closed-loop success.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  exit 0
fi

smoke_checkpoint="${ORCH_DIR}/rank32-roundtrip/pretrained_model"
python scripts/smoke_mobile_pi05_augmented_peft_rocm.py \
  --template-checkpoint "${r11_run}/checkpoints/012000/pretrained_model" \
  --output-dir "${smoke_checkpoint}" \
  --rank 32 \
  --alpha 32 \
  --num-steps 2 \
  --seed 20260728
python scripts/audit_mobile_pi05_checkpoint.py \
  "${smoke_checkpoint}" \
  --require-state-token \
  --require-mode-head \
  --require-contract \
  --expected-lora-rank 32 \
  --expected-lora-alpha 32 \
  --output "${ORCH_DIR}/rank32-roundtrip/static-audit.json"

launch_json="$(env \
  MOBILE_PI05_MODE_LOSS_WEIGHT=1 \
  MOBILE_PI05_MODE_CE_WEIGHT=0 \
  MOBILE_PI05_STATE_TOKEN=1 \
  MOBILE_PI05_MODE_HEAD=1 \
  MOBILE_PI05_MODE_HEAD_CE_WEIGHT=2 \
  MOBILE_PI05_MODE_HEAD_CLASS_WEIGHTS=0.7608864696734059,0.920075223319229,1.6697952218430034 \
  MOBILE_PI05_LORA_R=32 \
  MOBILE_PI05_LORA_ALPHA=32 \
  MOBILE_PI05_SAVE_FREQ=3000 \
  bash scripts/launch_mobile_pi05_training_rocm.sh \
    "${DATASET_ROOT}" "${R12_RUN}" "${R12_LOG}" 12000)"
printf '%s\n' "${launch_json}"
r12_pid="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["pid"])' "${launch_json}")"

screen_log="${ORCH_DIR}/r12-postscreen.log"
nohup bash scripts/postscreen_mobile_pi05_training_rocm.sh \
  "${r12_pid}" "${R12_LOG}" "${R12_RUN}" "${DATASET_ROOT}" \
  "${R12_EVAL}" "pi05-r12-fused-head-state-token-rank32" 3000 6000 9000 12000 \
  >"${screen_log}" 2>&1 </dev/null &
r12_screen_pid=$!
printf '%s\n' "${r12_screen_pid}" >"${screen_log}.pid"

python - "${ORCH_DIR}/DECISION.json" "${decision}" "${launch_json}" "${r12_screen_pid}" <<'PY'
import json
from pathlib import Path
import sys

payload = {
    "schema_version": 1,
    "protocol": "pi05-r11-to-r12-gate-v1",
    "decision": "launch_r12_rank32",
    "r11_screen": json.loads(sys.argv[2]),
    "rank32_roundtrip_report": "rank32-roundtrip/pretrained_model/PI05_AUGMENTED_PEFT_SMOKE.json",
    "rank32_static_audit": "rank32-roundtrip/static-audit.json",
    "r12_launch": json.loads(sys.argv[3]),
    "r12_postscreen_pid": int(sys.argv[4]),
    "r12_state_token_enabled": True,
    "r12_fused_mode_head_enabled": True,
    "r12_lora_rank": 32,
    "r12_lora_alpha": 32,
    "expert_fallback_allowed": False,
    "claim_boundary": "R12 launch and memory smoke are not routing, held-out generalization, or closed-loop capability evidence.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
