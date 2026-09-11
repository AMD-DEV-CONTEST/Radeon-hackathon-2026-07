#!/usr/bin/env bash
# Wait for the complete B1 pipeline to release the Radeon, then launch B2.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
B1_AUTO_PID="${1:?usage: $0 B1_AUTO_PID}"
STATUS_PATH="${ROOT_DIR}/outputs/pi05-b2-after-b1-status-v1.json"

if [[ ! "${B1_AUTO_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: B1_AUTO_PID must be a positive integer" >&2
  exit 2
fi
if [[ -e "${STATUS_PATH}" ]]; then
  echo "ERROR: B2 handoff status already exists: ${STATUS_PATH}" >&2
  exit 3
fi

while kill -0 "${B1_AUTO_PID}" 2>/dev/null; do
  sleep 60
done

pipeline_result="$(
  bash "${ROOT_DIR}/scripts/launch_mobile_pi05_b2_full_projection_pipeline_rocm.sh"
)"
printf '{"status":"b2_launched","b1_auto_pid":%s,"pipeline":%s}\n' \
  "${B1_AUTO_PID}" "${pipeline_result}" >"${STATUS_PATH}"
cat "${STATUS_PATH}"
