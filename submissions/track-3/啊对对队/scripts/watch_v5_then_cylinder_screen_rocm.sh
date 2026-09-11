#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
V5_OUTPUT_ROOT="${1:?usage: watch_v5_then_cylinder_screen_rocm.sh V5_OUTPUT_ROOT CYLINDER_OUTPUT_ROOT}"
CYLINDER_OUTPUT_ROOT="${2:?usage: watch_v5_then_cylinder_screen_rocm.sh V5_OUTPUT_ROOT CYLINDER_OUTPUT_ROOT}"
POLL_SECONDS="${WATCH_POLL_SECONDS:-30}"
RESULT_GRACE_SECONDS="${WATCH_RESULT_GRACE_SECONDS:-60}"
V5_PID_FILE="${V5_OUTPUT_ROOT}/run.pid"
V5_RESULT="${V5_OUTPUT_ROOT}/confirmation-result.json"
CYLINDER_RESULT="${CYLINDER_OUTPUT_ROOT}/result.json"
LOCK_FILE="${CYLINDER_OUTPUT_ROOT}.handoff.lock"

if ! [[ "${POLL_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: WATCH_POLL_SECONDS must be a positive integer" >&2
  exit 64
fi
if ! [[ "${RESULT_GRACE_SECONDS}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: WATCH_RESULT_GRACE_SECONDS must be a non-negative integer" >&2
  exit 64
fi
if [[ ! -f "${V5_PID_FILE}" ]]; then
  echo "ERROR: V5 PID file not found: ${V5_PID_FILE}" >&2
  exit 2
fi

mkdir -p "$(dirname "${CYLINDER_OUTPUT_ROOT}")"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "ERROR: another V5-to-cylinder handoff owns ${LOCK_FILE}" >&2
  exit 3
fi

if [[ -f "${CYLINDER_RESULT}" ]]; then
  echo "[$(date -Is)] cylinder screen already has a final result: ${CYLINDER_RESULT}"
  exit 0
fi

read -r v5_pid < "${V5_PID_FILE}"
if ! [[ "${v5_pid}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: invalid V5 PID in ${V5_PID_FILE}: ${v5_pid}" >&2
  exit 4
fi

echo "[$(date -Is)] waiting for V5 PID ${v5_pid}"
while kill -0 "${v5_pid}" 2>/dev/null; do
  sleep "${POLL_SECONDS}"
done

remaining="${RESULT_GRACE_SECONDS}"
while [[ ! -f "${V5_RESULT}" && "${remaining}" -gt 0 ]]; do
  sleep 1
  remaining=$((remaining - 1))
done
if [[ ! -f "${V5_RESULT}" ]]; then
  echo "ERROR: V5 exited without a final result: ${V5_RESULT}" >&2
  exit 5
fi

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
python - "${V5_RESULT}" <<'PY'
import json
from collections.abc import Mapping
from pathlib import Path
import sys

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
decision = payload.get("decision")
if not isinstance(decision, Mapping):
    raise SystemExit("V5 result is missing its decision object")
status = decision.get("status")
if status not in {"confirmation_passed", "confirmation_failed"}:
    raise SystemExit(f"V5 result has an unexpected decision status: {status!r}")
print(f"validated V5 final result: status={status} path={path}")
PY

echo "[$(date -Is)] V5 is final; checking the single Radeon before handoff"
bash scripts/preflight_radeon.sh

echo "[$(date -Is)] starting frozen cylinder static screen"
PYTHONPATH=src python scripts/run_cylinder_static_screen.py \
  --protocol configs/cylinder_static_screen_v1.toml \
  --output-dir "${CYLINDER_OUTPUT_ROOT}" \
  --backend rocm \
  --resume

echo "[$(date -Is)] cylinder static screen finished: ${CYLINDER_RESULT}"
