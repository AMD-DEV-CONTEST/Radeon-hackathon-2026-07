#!/usr/bin/env bash
# Continue with the single-factor DROID initialization only when B0 is negative.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
B0_AUTO_PID="${1:?usage: $0 B0_AUTO_PID}"
B0_GATE="${2:-${ROOT_DIR}/outputs/pi05-b0-absolute-strict-dev-v1/STRICT_GATE.json}"

if [[ ! "${B0_AUTO_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: B0_AUTO_PID must be a positive integer" >&2
  exit 2
fi
while kill -0 "${B0_AUTO_PID}" 2>/dev/null; do
  sleep 60
done

if [[ -f "${B0_GATE}" ]] && python - "${B0_GATE}" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("status") == "passed" else 1)
PY
then
  printf '{"status":"skipped","reason":"b0_strict_development_passed","gate":"%s"}\n' \
    "${B0_GATE}"
  exit 0
fi

bash "${ROOT_DIR}/scripts/launch_mobile_pi05_b1_droid_pipeline_rocm.sh"
