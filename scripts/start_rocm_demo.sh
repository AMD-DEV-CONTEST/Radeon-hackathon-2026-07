#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-configs/app.yaml}"

if ! command -v rocminfo >/dev/null 2>&1; then
  echo "ROCm unavailable: rocminfo was not found." >&2
  exit 2
fi

if [ "${BUILDGUARD_LLM__MODE:-}" != "local" ]; then
  echo "Set BUILDGUARD_LLM__MODE=local and a local BUILDGUARD_LLM__ENDPOINT." >&2
  exit 2
fi

if [ -z "${BUILDGUARD_LLM__ENDPOINT:-}" ]; then
  echo "BUILDGUARD_LLM__ENDPOINT is required (for example http://127.0.0.1:8080/v1)." >&2
  exit 2
fi

python -m buildguard.cli probe-environment --config "$CONFIG_PATH"
exec python -m buildguard.cli run-demo --config "$CONFIG_PATH"
