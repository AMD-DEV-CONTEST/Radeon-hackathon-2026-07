#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV=${VENV:?set VENV to the ROCm Python environment}
ROCM_ROOT=${ROCM_ROOT:-/opt/rocm-7.2.1}
ROCM_WRAPPER=${ROCM_WRAPPER:-${AMD_BIGYM_ROOT:-/workspace/amd-bigym-3dgs}/toolchains/rocm-wrapper}
PYTORCH_ROCM_ARCH=${PYTORCH_ROCM_ARCH:-gfx1100}
TORCH_EXTENSIONS_DIR=${TORCH_EXTENSIONS_DIR:-${AMD_BIGYM_ROOT:-/workspace/amd-bigym-3dgs}/cache/torch-extensions-gsplat}

test -x "$VENV/bin/python" || { printf 'Missing Python: %s\n' "$VENV/bin/python" >&2; exit 2; }
ROCM_ROOT="$ROCM_ROOT" ROCM_WRAPPER="$ROCM_WRAPPER" \
  "$REPO_ROOT/scripts/create_rocm_wrapper.sh"

"$VENV/bin/python" -m pip install --no-deps 'gsplat==1.4.0'
SITE_ROOT=$("$VENV/bin/python" - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)

if patch --dry-run --forward -d "$SITE_ROOT" -p1 \
    < "$REPO_ROOT/patches/gsplat-1.4.0-rocm-gfx1100.patch" >/dev/null; then
  patch --forward -d "$SITE_ROOT" -p1 \
    < "$REPO_ROOT/patches/gsplat-1.4.0-rocm-gfx1100.patch"
elif patch --dry-run --reverse -d "$SITE_ROOT" -p1 \
    < "$REPO_ROOT/patches/gsplat-1.4.0-rocm-gfx1100.patch" >/dev/null; then
  printf 'gsplat ROCm patch is already applied.\n'
else
  printf 'gsplat source does not match the pinned 1.4.0 patch.\n' >&2
  exit 2
fi

export ROCM_HOME="$ROCM_WRAPPER"
export PATH="$ROCM_WRAPPER/bin:$PATH"
export PYTORCH_ROCM_ARCH
export TORCH_EXTENSIONS_DIR
export MAX_JOBS=${MAX_JOBS:-1}
export CPLUS_INCLUDE_PATH="$SITE_ROOT/gsplat/cuda/csrc/third_party/glm${CPLUS_INCLUDE_PATH:+:$CPLUS_INCLUDE_PATH}"
mkdir -p "$TORCH_EXTENSIONS_DIR"
"$VENV/bin/python" "$REPO_ROOT/scripts/smoke_test_gsplat.py"
