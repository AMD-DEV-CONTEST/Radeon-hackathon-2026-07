#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"
cd "$BG_REPO"
"$BG_VENV/bin/python" scripts/verify_amd_dependencies.py --profile evaluation \
  | tee "$BG_ARTIFACTS/amd-dependencies.json"
"$BG_VENV/bin/python" scripts/server_probe.py | tee "$BG_ARTIFACTS/server-probe.json"
