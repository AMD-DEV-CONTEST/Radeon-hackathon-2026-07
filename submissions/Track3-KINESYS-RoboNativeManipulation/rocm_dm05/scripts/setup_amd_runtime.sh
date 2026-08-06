#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
THIRD_PARTY=${1:-$PROJECT_ROOT/third_party}
: "${VENV:?Set VENV to an existing Python environment with ROCm PyTorch}"

test -x "$VENV/bin/python" || { echo "Missing Python: $VENV/bin/python" >&2; exit 2; }
"$VENV/bin/python" - <<'PY'
import torch
if torch.version.hip is None or not torch.cuda.is_available():
    raise SystemExit("The selected environment does not contain working ROCm PyTorch")
PY

bash "$PROJECT_ROOT/scripts/setup_sources.sh" "$THIRD_PARTY"
OPENDM_ROOT="$THIRD_PARTY/opendm"
BIGYM_3DGS_ROOT="$THIRD_PARTY/amd-bigym-3dgs-rocm"
BIGYM_ROOT="$THIRD_PARTY/bigym"

"$VENV/bin/python" -m pip install -r "$PROJECT_ROOT/requirements-amd.txt"
"$VENV/bin/python" -m pip install --no-deps -e "$OPENDM_ROOT"

BIGYM_3DGS_ROOT="$BIGYM_3DGS_ROOT" BIGYM_ROOT="$BIGYM_ROOT" VENV="$VENV" \
  bash "$PROJECT_ROOT/scripts/install_bigym_amd_overlay.sh"

VENV="$VENV" BIGYM_3DGS_ROOT="$BIGYM_3DGS_ROOT" \
  bash "$PROJECT_ROOT/scripts/build_3dgs_rocm.sh"

ROCM_HOME="$BIGYM_3DGS_ROOT/toolchains/rocm-wrapper" \
PATH="$BIGYM_3DGS_ROOT/toolchains/rocm-wrapper/bin:$PATH" \
TORCH_EXTENSIONS_DIR="$BIGYM_3DGS_ROOT/cache/torch-extensions-gsplat" \
PYTORCH_ROCM_ARCH=${PYTORCH_ROCM_ARCH:-gfx1100} MAX_JOBS=${MAX_JOBS:-4} \
CPLUS_INCLUDE_PATH="$PROJECT_ROOT/compat/include${CPLUS_INCLUDE_PATH:+:$CPLUS_INCLUDE_PATH}" \
  "$VENV/bin/python" "$PROJECT_ROOT/scripts/preflight_amd.py" \
    --require-training --require-3dgs

echo "OPENDM_ROOT=$OPENDM_ROOT"
echo "BIGYM_ROOT=$BIGYM_ROOT"
echo "BIGYM_3DGS_ROOT=$BIGYM_3DGS_ROOT"
