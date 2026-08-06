#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

for script in "$EVAL_DIR"/bin/*.sh; do
  bash -n "$script"
done
python3 -m compileall -q "$EVAL_DIR/src" "$EVAL_DIR/tests"
python3 -m unittest discover -s "$EVAL_DIR/tests" -v
printf 'BIGYM_3DGS_EVAL_CONTRACT_OK\n'
