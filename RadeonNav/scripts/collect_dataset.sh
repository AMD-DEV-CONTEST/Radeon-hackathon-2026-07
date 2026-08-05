#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 {ft1|ft2} OUTPUT_DIR [DEPTH_ENCODER_CHECKPOINT]" >&2
  exit 2
fi

PHASE=$1
OUTPUT_DIR=$2
CHECKPOINT=${3:-}
JOBS=${JOBS:-4}
DEVICE=${DEVICE:-cuda}

case "$PHASE" in
  ft1)
    RECIPE_DIR="$RADEONNAV_ROOT/experiment-results/quadrupedal-agility/FT1-DATA"
    EXPECTED_COUNT=159
    ;;
  ft2)
    RECIPE_DIR="$RADEONNAV_ROOT/experiment-results/quadrupedal-agility/FT2-DATA"
    EXPECTED_COUNT=119
    if [[ -z $CHECKPOINT ]]; then
      echo "ft2 recollection requires the FT1-trained checkpoint as argument 3" >&2
      exit 2
    fi
    ;;
  *)
    echo "phase must be ft1 or ft2" >&2
    exit 2
    ;;
esac

COMMAND=(
  "$RADEONNAV_ROOT/experiments/neupan_agility/mrocm_collect.py"
  --recipe-dir "$RECIPE_DIR"
  --output-dir "$OUTPUT_DIR"
  --expected-count "$EXPECTED_COUNT"
  --jobs "$JOBS"
  --device "$DEVICE"
)
if [[ -n $CHECKPOINT ]]; then
  COMMAND+=(--depth-encoder-checkpoint "$CHECKPOINT")
fi

run_python "${COMMAND[@]}"

