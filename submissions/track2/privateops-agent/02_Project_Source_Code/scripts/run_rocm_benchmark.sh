#!/usr/bin/env bash
set -euo pipefail

eval "$(python3 -m privateops.rocm_profile)"
python3 scripts/collect_rocm_evidence.py \
  --app-url "${PRIVATEOPS_APP_URL:-http://127.0.0.1:8765}" \
  --model-endpoint "$PRIVATEOPS_MODEL_ENDPOINT" \
  --model-name "$PRIVATEOPS_MODEL_NAME"
