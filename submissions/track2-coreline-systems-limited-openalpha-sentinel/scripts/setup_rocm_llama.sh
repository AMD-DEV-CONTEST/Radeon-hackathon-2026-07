#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/scripts/lib/env.sh"
openalpha_load_env "$ROOT_DIR" runtime optional

LLAMA_SOURCE="${LLAMA_SOURCE:-$ROOT_DIR/vendor/llama.cpp}"
LLAMA_BUILD="${LLAMA_BUILD:-$LLAMA_SOURCE/build}"
AMDGPU_TARGETS="${AMDGPU_TARGETS:-gfx1100}"
BUILD_JOBS="${BUILD_JOBS:-16}"

if [[ ! -d "$LLAMA_SOURCE" ]]; then
  echo "llama.cpp source is missing at $LLAMA_SOURCE" >&2
  echo "Upload ROCm/llama.cpp commit 1b99711a5f2582ec99686eb7958844749c223cf5 first." >&2
  exit 1
fi

openalpha_require_commands cmake hipconfig
export HIPCXX="${HIPCXX:-$(hipconfig -l)/clang}"
export HIP_PATH="${HIP_PATH:-$(hipconfig -R)}"

cmake -S "$LLAMA_SOURCE" -B "$LLAMA_BUILD" \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS="$AMDGPU_TARGETS" \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLAMA_CURL=OFF
cmake --build "$LLAMA_BUILD" --config Release -j"$BUILD_JOBS"

"$LLAMA_BUILD/bin/llama-server" --version
