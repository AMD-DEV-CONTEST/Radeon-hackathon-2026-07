#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

if [[ $# -ne 2 ]]; then
  echo "usage: $0 TRAIN_DIR OUTPUT_DIR" >&2
  exit 2
fi

JOBS=${JOBS:-4}
DEVICE=${DEVICE:-cuda}
run_python "$RADEONNAV_ROOT/experiments/neupan_agility/mrocm_select.py" \
  --train-dir "$1" \
  --output-dir "$2" \
  --jobs "$JOBS" \
  --device "$DEVICE"

