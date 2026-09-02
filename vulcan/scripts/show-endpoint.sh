#!/usr/bin/env bash
# Print what the configured backend is actually serving. Kept out of the VHS
# tape because its Type command cannot carry nested quotes.
set -euo pipefail
curl -s "$VULCAN_BASE_URL/models" -H "Authorization: Bearer $VULCAN_API_KEY" \
  | python3 -c 'import sys, json; d = json.load(sys.stdin)["data"][0]; print("served model:", d["id"]); print("context length:", d["max_model_len"]); print("served by:", d["owned_by"])'
