#!/usr/bin/env bash
set -euo pipefail

RADEONNAV_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
exec "$RADEONNAV_ROOT/scripts/run_mpax_rocm.sh" \
  "$RADEONNAV_ROOT/NeuPAN/example/nrmp_mpax_rocm_smoke.py" "$@"
