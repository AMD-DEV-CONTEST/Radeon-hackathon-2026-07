#!/usr/bin/env bash
# Select B0 deterministically after post-screening, then run the strict dev gate.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POST_PID="${1:?usage: $0 POST_PID RUN_ROOT SCREEN_ROOT STRICT_OUTPUT [RUN_NAME RUN_ID]}"
RUN_ROOT="${2:?usage: $0 POST_PID RUN_ROOT SCREEN_ROOT STRICT_OUTPUT [RUN_NAME RUN_ID]}"
SCREEN_ROOT="${3:?usage: $0 POST_PID RUN_ROOT SCREEN_ROOT STRICT_OUTPUT [RUN_NAME RUN_ID]}"
STRICT_OUTPUT="${4:?usage: $0 POST_PID RUN_ROOT SCREEN_ROOT STRICT_OUTPUT [RUN_NAME RUN_ID]}"
RUN_NAME="${5:-pi05-b0-absolute}"
RUN_ID="${6:-b0}"
SELECTION="${SCREEN_ROOT}/CHECKPOINT_SELECTION.json"

if [[ ! "${POST_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: POST_PID must be a positive integer" >&2
  exit 2
fi
if [[ -e "${SELECTION}" || -e "${STRICT_OUTPUT}" ]]; then
  echo "ERROR: B0 selection or strict-development output already exists" >&2
  exit 3
fi

while kill -0 "${POST_PID}" 2>/dev/null; do
  sleep 60
done

screens=()
for step in 3000 6000 9000 12000; do
  screen="${SCREEN_ROOT}/${RUN_NAME}-step${step}-stage-panel-screen.json"
  if [[ ! -f "${screen}" ]]; then
    echo "ERROR: missing completed B0 route screen: ${screen}" >&2
    exit 4
  fi
  screens+=(--screen "${screen}")
done

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
python "${ROOT_DIR}/scripts/select_mobile_pi05_route_checkpoint.py" \
  "${screens[@]}" \
  --expected-count 4 \
  --output "${SELECTION}"

checkpoint="$(python - "${SELECTION}" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload["selected_checkpoint"])
PY
)"

bash "${ROOT_DIR}/scripts/run_mobile_pi05_b0_strict_dev_rocm.sh" \
  "${checkpoint}" "${STRICT_OUTPUT}" "${RUN_ID}"

printf '{"status":"complete","selection":"%s","checkpoint":"%s","strict_output":"%s"}\n' \
  "${SELECTION}" "${checkpoint}" "${STRICT_OUTPUT}"
