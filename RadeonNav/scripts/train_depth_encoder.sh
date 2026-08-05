#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 OUTPUT_DIR [DATA_DIR ...]" >&2
  exit 2
fi

OUTPUT_DIR=$1
shift
EPOCHS=${EPOCHS:-6}
DEVICE=${DEVICE:-cuda}

if [[ $# -eq 0 ]]; then
  DATA_DIRS=(
    "$RADEONNAV_ROOT/experiment-results/quadrupedal-agility/FT1-DATA"
    "$RADEONNAV_ROOT/experiment-results/quadrupedal-agility/FT2-DATA"
  )
else
  DATA_DIRS=("$@")
fi

run_python "$RADEONNAV_ROOT/experiments/neupan_agility/ft_train.py" \
  --data-dir "${DATA_DIRS[@]}" \
  --output-dir "$OUTPUT_DIR" \
  --epochs "$EPOCHS" \
  --save-every-epoch \
  --device "$DEVICE"

