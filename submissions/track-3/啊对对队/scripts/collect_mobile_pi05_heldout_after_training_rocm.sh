#!/usr/bin/env bash
# Collect the frozen observation panel only after all scheduled PI0.5 GPU work.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
R12_R13_PID="${1:?usage: $0 R12_R13_PID R12_R13_ORCH PANEL BLOCK COLLECTION ORCH_DIR}"
R12_R13_ORCH="${2:?usage: $0 R12_R13_PID R12_R13_ORCH PANEL BLOCK COLLECTION ORCH_DIR}"
PANEL="${3:?usage: $0 R12_R13_PID R12_R13_ORCH PANEL BLOCK COLLECTION ORCH_DIR}"
BLOCK="${4:?usage: $0 R12_R13_PID R12_R13_ORCH PANEL BLOCK COLLECTION ORCH_DIR}"
COLLECTION="${5:?usage: $0 R12_R13_PID R12_R13_ORCH PANEL BLOCK COLLECTION ORCH_DIR}"
ORCH_DIR="${6:?usage: $0 R12_R13_PID R12_R13_ORCH PANEL BLOCK COLLECTION ORCH_DIR}"

if [[ ! "${R12_R13_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: R12-to-R13 process ID must be a positive integer" >&2
  exit 2
fi
for path in "${COLLECTION}" "${ORCH_DIR}"; do
  if [[ -e "${path}" ]]; then
    echo "ERROR: output already exists: ${path}" >&2
    exit 3
  fi
done
for path in "${PANEL}" "${BLOCK}"; do
  if [[ ! -f "${path}" ]]; then
    echo "ERROR: frozen held-out input not found: ${path}" >&2
    exit 4
  fi
done

mkdir -p "${ORCH_DIR}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export TOKENIZERS_PARALLELISM=false
cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh >/dev/null

while kill -0 "${R12_R13_PID}" 2>/dev/null; do
  sleep 60
done
if [[ ! -f "${R12_R13_ORCH}/DECISION.json" ]]; then
  echo "ERROR: R12-to-R13 gate exited without a decision" >&2
  exit 5
fi

decision="$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["decision"])' "${R12_R13_ORCH}/DECISION.json")"
if [[ "${decision}" == "launch_r13_last_language_token" ]]; then
  readarray -t r13_pids < <(python - "${R12_R13_ORCH}/DECISION.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(int(payload["r13_launch"]["pid"]))
print(int(payload["r13_postscreen_pid"]))
PY
)
  for pid in "${r13_pids[@]}"; do
    while kill -0 "${pid}" 2>/dev/null; do
      sleep 60
    done
  done
elif [[ "${decision}" != "stop_before_r13" && "${decision}" != "run_r12_strict_development_closed_loop" ]]; then
  echo "ERROR: unsupported R12-to-R13 decision: ${decision}" >&2
  exit 6
fi

collection_log="${ORCH_DIR}/collection.log"
python scripts/collect_mobile_pi05_heldout_observations_rocm.py \
  --panel "${PANEL}" \
  --workspace-block "${BLOCK}" \
  --output "${COLLECTION}" \
  --backend rocm \
  --image-size 224 \
  >"${collection_log}" 2>&1

audit_path="${ORCH_DIR}/collection-audit.json"
python scripts/audit_mobile_pi05_heldout_collection.py \
  --collection "${COLLECTION}" \
  --panel "${PANEL}" \
  --workspace-block "${BLOCK}" \
  --output "${audit_path}"

python - "${ORCH_DIR}/DECISION.json" "${decision}" "${COLLECTION}" "${audit_path}" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

collection = Path(sys.argv[3]).resolve()
manifest = collection / "PI05_HELDOUT_OBSERVATION_MANIFEST.json"
audit = Path(sys.argv[4]).resolve()
payload = {
    "schema_version": 1,
    "protocol": "pi05-heldout-after-training-gate-v1",
    "decision": "heldout_initial_observations_collected",
    "upstream_decision": sys.argv[2],
    "collection": str(collection),
    "manifest": str(manifest),
    "manifest_sha256": sha256(manifest),
    "audit": str(audit),
    "audit_sha256": sha256(audit),
    "checkpoint_probed": False,
    "training_use_allowed": False,
    "claim_boundary": "Collection and integrity audit only; no checkpoint was selected or evaluated.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
