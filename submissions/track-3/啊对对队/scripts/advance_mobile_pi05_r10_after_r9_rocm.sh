#!/usr/bin/env bash
# Advance from the R9 flow-routing control to the R10 fused-head ablation.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
R9_TRAIN_PID="${1:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"
R9_SCREEN_PID="${2:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"
R9_RUN="${3:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"
R9_EVAL="${4:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"
DATASET_ROOT="${5:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"
R10_RUN="${6:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"
R10_LOG="${7:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"
R10_EVAL="${8:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"
ORCH_DIR="${9:?usage: $0 R9_TRAIN_PID R9_SCREEN_PID R9_RUN R9_EVAL DATASET R10_RUN R10_LOG R10_EVAL ORCH_DIR}"

for pid in "${R9_TRAIN_PID}" "${R9_SCREEN_PID}"; do
  if [[ ! "${pid}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: R9 process IDs must be positive integers" >&2
    exit 2
  fi
done
for path in "${R10_RUN}" "${R10_LOG}" "${R10_LOG}.pid" "${R10_EVAL}" "${ORCH_DIR}"; do
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

while kill -0 "${R9_TRAIN_PID}" 2>/dev/null; do
  sleep 60
done
while kill -0 "${R9_SCREEN_PID}" 2>/dev/null; do
  sleep 60
done

if [[ ! -f "${R9_RUN}/checkpoints/012000/pretrained_model/adapter_model.safetensors" ]]; then
  echo "ERROR: R9 did not produce the final checkpoint" >&2
  exit 4
fi

decision="$(python - "${R9_EVAL}" <<'PY'
import glob
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
paths = sorted(glob.glob(str(root / "*-six-observation-screen.json")))
if len(paths) != 4:
    raise SystemExit(f"expected four R9 screens, found {len(paths)}")
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

screen = json.loads(sys.argv[2])
payload = {
    "schema_version": 1,
    "protocol": "pi05-r9-to-r10-gate-v1",
    "decision": "run_r9_strict_development_closed_loop",
    "r9_screen": screen,
    "r10_launched": False,
    "claim_boundary": "A routing screen is not a closed-loop success result.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  exit 0
fi

smoke_checkpoint="${ORCH_DIR}/augmented-roundtrip/pretrained_model"
python scripts/smoke_mobile_pi05_augmented_peft_rocm.py \
  --template-checkpoint "${R9_RUN}/checkpoints/012000/pretrained_model" \
  --output-dir "${smoke_checkpoint}" \
  --rank 16 \
  --alpha 32 \
  --num-steps 2 \
  --seed 20260728
python scripts/audit_mobile_pi05_checkpoint.py \
  "${smoke_checkpoint}" \
  --require-state-token \
  --require-mode-head \
  --require-contract \
  --output "${ORCH_DIR}/augmented-roundtrip/static-audit.json"

launch_json="$(env \
  MOBILE_PI05_MODE_LOSS_WEIGHT=1 \
  MOBILE_PI05_MODE_CE_WEIGHT=0 \
  MOBILE_PI05_STATE_TOKEN=0 \
  MOBILE_PI05_MODE_HEAD=1 \
  MOBILE_PI05_MODE_HEAD_CE_WEIGHT=2 \
  MOBILE_PI05_MODE_HEAD_CLASS_WEIGHTS=0.7608864696734059,0.920075223319229,1.6697952218430034 \
  MOBILE_PI05_LORA_R=16 \
  MOBILE_PI05_LORA_ALPHA=32 \
  MOBILE_PI05_SAVE_FREQ=3000 \
  bash scripts/launch_mobile_pi05_training_rocm.sh \
    "${DATASET_ROOT}" "${R10_RUN}" "${R10_LOG}" 12000)"
printf '%s\n' "${launch_json}"
r10_pid="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["pid"])' "${launch_json}")"

screen_log="${ORCH_DIR}/r10-postscreen.log"
nohup bash scripts/postscreen_mobile_pi05_training_rocm.sh \
  "${r10_pid}" "${R10_LOG}" "${R10_RUN}" "${DATASET_ROOT}" \
  "${R10_EVAL}" "pi05-r10-fused-mode-head" 3000 6000 9000 12000 \
  >"${screen_log}" 2>&1 </dev/null &
r10_screen_pid=$!
printf '%s\n' "${r10_screen_pid}" >"${screen_log}.pid"

python - "${ORCH_DIR}/DECISION.json" "${decision}" "${launch_json}" "${r10_screen_pid}" <<'PY'
import json
from pathlib import Path
import sys

payload = {
    "schema_version": 1,
    "protocol": "pi05-r9-to-r10-gate-v1",
    "decision": "launch_r10_fused_mode_head",
    "r9_screen": json.loads(sys.argv[2]),
    "roundtrip_report": "augmented-roundtrip/pretrained_model/PI05_AUGMENTED_PEFT_SMOKE.json",
    "static_audit": "augmented-roundtrip/static-audit.json",
    "r10_launch": json.loads(sys.argv[3]),
    "r10_postscreen_pid": int(sys.argv[4]),
    "r10_state_token_enabled": False,
    "r10_fused_mode_head_enabled": True,
    "expert_fallback_allowed": False,
    "claim_boundary": "R10 launch is not routing or closed-loop capability evidence.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
