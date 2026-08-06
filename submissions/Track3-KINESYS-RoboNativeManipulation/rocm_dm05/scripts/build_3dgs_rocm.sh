#!/usr/bin/env bash
set -euo pipefail

: "${VENV:?Set VENV to the ROCm Python environment}"
: "${BIGYM_3DGS_ROOT:?Set BIGYM_3DGS_ROOT to eust-w/amd-bigym-3dgs-rocm}"

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ROCM_ROOT=${ROCM_ROOT:-/opt/rocm-7.2.1}
ROCM_WRAPPER=${ROCM_WRAPPER:-$BIGYM_3DGS_ROOT/toolchains/rocm-wrapper}
TORCH_EXTENSIONS_DIR=${TORCH_EXTENSIONS_DIR:-$BIGYM_3DGS_ROOT/cache/torch-extensions-gsplat}
PYTORCH_ROCM_ARCH=${PYTORCH_ROCM_ARCH:-gfx1100}

test -x "$VENV/bin/python" || { echo "Missing Python: $VENV/bin/python" >&2; exit 2; }
test -f /usr/include/glm/glm.hpp || {
  echo "Missing GLM headers. Install the libglm-dev system package." >&2
  exit 2
}

ROCM_ROOT="$ROCM_ROOT" ROCM_WRAPPER="$ROCM_WRAPPER" \
  bash "$BIGYM_3DGS_ROOT/scripts/create_rocm_wrapper.sh"
"$VENV/bin/python" -m pip install --no-deps "gsplat==1.4.0"

SITE_ROOT=$("$VENV/bin/python" - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)
GSPLAT_PATCH="$BIGYM_3DGS_ROOT/patches/gsplat-1.4.0-rocm-gfx1100.patch"
if patch --dry-run --forward -d "$SITE_ROOT" -p1 < "$GSPLAT_PATCH" >/dev/null; then
  patch --forward -d "$SITE_ROOT" -p1 < "$GSPLAT_PATCH"
elif patch --dry-run --reverse -d "$SITE_ROOT" -p1 < "$GSPLAT_PATCH" >/dev/null; then
  echo "gsplat ROCm patch is already applied"
else
  echo "gsplat source does not match the pinned ROCm patch" >&2
  exit 2
fi

"$VENV/bin/python" - "$SITE_ROOT/gsplat/cuda/csrc/types.cuh" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
block = """template <> struct OpType<__nv_bfloat16> {
    typedef float type;
};

"""
if block in text:
    path.write_text(text.replace(block, "", 1), encoding="utf-8")
elif "OpType<c10::BFloat16>" not in text:
    raise SystemExit("Unexpected gsplat bf16 type definitions")
PY

export ROCM_HOME="$ROCM_WRAPPER"
export PATH="$ROCM_WRAPPER/bin:$PATH"
export PYTORCH_ROCM_ARCH
export TORCH_EXTENSIONS_DIR
export MAX_JOBS=${MAX_JOBS:-4}
export CPLUS_INCLUDE_PATH="$PROJECT_ROOT/compat/include:/usr/include${CPLUS_INCLUDE_PATH:+:$CPLUS_INCLUDE_PATH}"
mkdir -p "$TORCH_EXTENSIONS_DIR"
"$VENV/bin/python" "$BIGYM_3DGS_ROOT/scripts/smoke_test_gsplat.py"
