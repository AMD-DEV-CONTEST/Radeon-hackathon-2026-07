#!/usr/bin/env bash
set -euo pipefail

eval "$(python3 -m privateops.rocm_profile)"
export PRIVATEOPS_PROVIDER_MODE="rocm-local"
export PRIVATEOPS_WORKSPACE_DIR="${PRIVATEOPS_WORKSPACE_DIR:-$(pwd)}"
export PRIVATEOPS_KNOWLEDGE_DIR="${PRIVATEOPS_KNOWLEDGE_DIR:-$(pwd)/data/knowledge}"
export PRIVATEOPS_STATE_DIR="${PRIVATEOPS_STATE_DIR:-$(pwd)/data/state}"

curl --fail --silent "$PRIVATEOPS_MODELS_ENDPOINT" >/dev/null
exec python3 -m privateops.server
