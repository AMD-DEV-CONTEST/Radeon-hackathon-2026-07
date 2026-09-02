#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(uname -s)" == Linux ]] || { echo "Linux is required."; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo "x86_64 is required."; exit 1; }
command -v python3 >/dev/null || { echo "Python 3.11+ is required."; exit 1; }
python3 -c "import sys; raise SystemExit(sys.version_info < (3,11))" || { echo "Python 3.11+ is required."; exit 1; }
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-deps \
  -r "$ROOT/app/backend/requirements.txt"
[[ -f "$ROOT/app/frontend/index.html" ]] || { echo "Frontend build is missing."; exit 1; }
mkdir -p "$ROOT/config" "$ROOT/data" "$ROOT/logs"
chmod 700 "$ROOT/config" "$ROOT/data" "$ROOT/logs"
if command -v rocminfo >/dev/null; then echo "ROCm: PASS"; else echo "AMD/ROCm not detected. Provider endpoints and Fake mode remain available."; fi
echo "AlphaNoah dependencies ready. Run ./scripts/configure.sh"
