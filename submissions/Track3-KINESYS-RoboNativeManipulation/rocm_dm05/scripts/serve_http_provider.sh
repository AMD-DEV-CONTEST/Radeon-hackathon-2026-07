#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 MODEL_PATH MODEL_ID MODEL_REVISION [provider arguments...]" >&2
  exit 2
fi

MODEL_PATH=$1
MODEL_ID=$2
MODEL_REVISION=$3
shift 3
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

: "${PYTHON:?Set PYTHON to the ROCm environment Python executable}"
: "${OPENDM_ROOT:?Set OPENDM_ROOT to the patched OpenDM checkout}"

export PYTHONPATH="$PROJECT_ROOT/inference:$PROJECT_ROOT/train:$OPENDM_ROOT:$OPENDM_ROOT/d${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON" "$PROJECT_ROOT/inference/http_provider.py" \
  --model-path "$MODEL_PATH" \
  --model-id "$MODEL_ID" \
  --model-revision "$MODEL_REVISION" \
  --host "${INFERENCE_HOST:-127.0.0.1}" \
  --port "${INFERENCE_PORT:-7891}" \
  "$@"
