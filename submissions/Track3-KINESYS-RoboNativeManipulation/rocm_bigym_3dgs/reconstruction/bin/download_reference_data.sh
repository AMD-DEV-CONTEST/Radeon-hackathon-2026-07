#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PYTHON=${PYTHON:-python3}
OUTPUT=${OUTPUT:-"$REPO_ROOT/data/private/dl3dv-kitchen"}

"$PYTHON" "$REPO_ROOT/reconstruction/src/download_dl3dv_scene.py" \
  --output "$OUTPUT" \
  --scene commercial-kitchen

printf 'Reference source verified at %s\n' "$OUTPUT"
