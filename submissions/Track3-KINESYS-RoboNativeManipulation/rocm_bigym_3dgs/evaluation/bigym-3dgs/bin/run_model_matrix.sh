#!/usr/bin/env bash
set -euo pipefail

EVAL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

exec python3 "$EVAL_DIR/src/run_model_matrix.py" "$@"
