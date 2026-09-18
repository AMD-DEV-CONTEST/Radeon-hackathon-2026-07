#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$BG_ARTIFACTS/runtime-evidence-$timestamp"
mkdir -p "$destination"
cp -a "$BG_LOGS/." "$destination/logs/"
cp -a "$BG_RUN/." "$destination/run/"
"$SCRIPT_DIR/server_probe.sh" >"$destination/server-probe.json"
"$SCRIPT_DIR/health_check.sh" >"$destination/health.txt"
find "$BG_MODELS" -type f -name '*manifest*.json' -print0 \
  | xargs -0 -r sha256sum >"$destination/model-manifest-sha256.txt"
tar -C "$BG_ARTIFACTS" -czf "$destination.tar.gz" "$(basename "$destination")"
echo "$destination.tar.gz"
