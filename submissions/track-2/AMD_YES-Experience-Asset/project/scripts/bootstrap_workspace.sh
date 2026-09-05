#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"

if [[ "$(pwd)" != /workspace* && "${ALLOW_NON_PERSISTENT:-0}" != "1" ]]; then
  echo "ERROR: Radeon Cloud only guarantees persistence under /workspace."
  echo "Run this script from /workspace, or set ALLOW_NON_PERSISTENT=1 for a local dry run."
  exit 1
fi

mkdir -p \
  "$ROOT/app" \
  "$ROOT/benchmarks" \
  "$ROOT/cache/huggingface" \
  "$ROOT/data/public" \
  "$ROOT/data/private" \
  "$ROOT/logs" \
  "$ROOT/models" \
  "$ROOT/venvs"

echo "Persistent Track 2 workspace prepared at: $ROOT"
echo "Next: copy this repository into $ROOT, then run scripts/verify_rocm_env.sh."
