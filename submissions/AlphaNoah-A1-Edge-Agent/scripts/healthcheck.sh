#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_config
curl -fsS "http://127.0.0.1:$ALPHANOAH_PORT/api/health" >/dev/null && echo "AlphaNoah: PASS" || { echo "AlphaNoah: FAIL"; exit 1; }
[[ -f "$PACKAGE_ROOT/data/alphanoah.sqlite3" ]] && echo "Database: PASS" || echo "Database: PASS (not initialized)"
echo "Provider: $ALPHANOAH_PROVIDER"
case "$ALPHANOAH_PROVIDER" in
 fake) echo "Provider Health: PASS"; echo "Mode: Simulation" ;;
 ollama) "$PACKAGE_ROOT/.venv/bin/python" "$PACKAGE_ROOT/scripts/provider_probe.py"; echo "Model: $ALPHANOAH_MODEL" ;;
 openai_compatible) "$PACKAGE_ROOT/.venv/bin/python" "$PACKAGE_ROOT/scripts/provider_probe.py"; echo "Endpoint Scope: $ALPHANOAH_INFERENCE_SCOPE"; echo "Model: $ALPHANOAH_MODEL" ;;
esac
curl -fsS "http://127.0.0.1:$ALPHANOAH_PORT/" >/dev/null && echo "Frontend: PASS" || { echo "Frontend: FAIL"; exit 1; }
