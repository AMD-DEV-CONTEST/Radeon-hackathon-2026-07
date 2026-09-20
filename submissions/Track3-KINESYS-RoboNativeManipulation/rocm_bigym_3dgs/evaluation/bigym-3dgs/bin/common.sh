#!/usr/bin/env bash
set -euo pipefail

EVAL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REPO_ROOT=$(cd "$EVAL_DIR/../.." && pwd)
AMD_PIPELINE_ROOT=${AMD_PIPELINE_ROOT:-${AMD_EVAL_ROOT:-/workspace/amd-bigym-3dgs-rocm}}
# Backward-compatible alias for existing deployments and archived receipts.
AMD_EVAL_ROOT=$AMD_PIPELINE_ROOT
BIGYM_DIR=${BIGYM_DIR:-$AMD_PIPELINE_ROOT/src/bigym_plus}
SHELL_DIR=${SHELL_DIR:-$AMD_PIPELINE_ROOT/artifacts/amd-kitchen-shell}
RESULTS_ROOT=${RESULTS_ROOT:-$AMD_PIPELINE_ROOT/results}
RUNTIME_EVIDENCE_DIR=${RUNTIME_EVIDENCE_DIR:-$RESULTS_ROOT/runtime}
BIGYM_PYTHON=${BIGYM_PYTHON:-${VENV:-$AMD_PIPELINE_ROOT/bigym-venv}/bin/python}
INFERENCE_PORT=${INFERENCE_PORT:-7891}
INFERENCE_HOST=${INFERENCE_HOST:-127.0.0.1}
INFERENCE_BASE_URL=${INFERENCE_BASE_URL:-http://$INFERENCE_HOST:$INFERENCE_PORT}
INFERENCE_GPU=${INFERENCE_GPU:-0}
INFERENCE_PROVIDER=${INFERENCE_PROVIDER:-external}
SIM_GPU=${SIM_GPU:-$INFERENCE_GPU}

BIGYM_REPOSITORY=https://github.com/WuChao-2024/bigym_plus.git
BIGYM_COMMIT=d12937686833467b5013ac47a834cf4b6f5a9d53
SHELL_REPOSITORY=eustance/amd-bigym-3dgs-kitchen-shell
SHELL_REVISION=amd-rocm-w7900d-20260804

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null || fail "required command is unavailable: $1"
}

clone_pinned() {
  local repository=$1
  local commit=$2
  local destination=$3
  if test ! -d "$destination/.git"; then
    mkdir -p "$(dirname "$destination")"
    git clone --filter=blob:none "$repository" "$destination"
  fi
  test -z "$(git -C "$destination" status --porcelain)" \
    || fail "refusing to change dirty checkout: $destination"
  git -C "$destination" fetch origin "$commit"
  git -C "$destination" checkout --detach "$commit"
  git -C "$destination" submodule update --init --recursive
  test "$(git -C "$destination" rev-parse HEAD)" = "$commit" \
    || fail "commit lock failed for $destination"
}
