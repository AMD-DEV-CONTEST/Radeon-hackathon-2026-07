#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

test -d "$BIGYM_DIR/.git" || fail "run bootstrap_bigym_source.sh first"

BIGYM_VENV=${VENV:-$AMD_PIPELINE_ROOT/bigym-venv}
BASE_PYTHON=${BASE_PYTHON:-python3.12}
require_command "$BASE_PYTHON"

if test ! -x "$BIGYM_VENV/bin/python"; then
  "$BASE_PYTHON" -m venv --system-site-packages "$BIGYM_VENV"
fi

"$BIGYM_VENV/bin/python" - <<'PY'
import torch
print("torch", torch.__version__)
print("hip", torch.version.hip)
print("device", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
if torch.version.hip is None or not torch.cuda.is_available():
    raise SystemExit(
        "The base image must provide a ROCm-enabled PyTorch build before BiGym setup"
    )
PY

"$BIGYM_VENV/bin/python" -m pip install --upgrade pip
"$BIGYM_VENV/bin/python" -m pip install -e "$BIGYM_DIR[examples,visual-shell]" \
  requests==2.34.2
# BiGym's extras currently allow a newer gsplat Python API than the pinned HIP
# extension in this repository. Keep both halves on 1.4.0; otherwise a fresh
# install can fail at runtime with a missing projection_ewa_3dgs_fused_fwd.
"$BIGYM_VENV/bin/python" -m pip install --no-deps gsplat==1.4.0

VENV="$BIGYM_VENV" \
ROCM_ROOT=${ROCM_ROOT:-/opt/rocm} \
PYTORCH_ROCM_ARCH=gfx1100 \
  "$REPO_ROOT/scripts/build_gsplat_rocm.sh"

ROCR_VISIBLE_DEVICES=$SIM_GPU HIP_VISIBLE_DEVICES=$SIM_GPU \
  "$BIGYM_VENV/bin/python" - <<'PY'
import torch
import gsplat
import bigym
print("BIGYM_RUNTIME_OK", bigym.__file__, gsplat.__file__, torch.cuda.get_device_name(0))
PY
