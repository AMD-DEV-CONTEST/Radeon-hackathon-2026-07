#!/usr/bin/env bash
set -euo pipefail

ROCM_ROOT=${ROCM_ROOT:-/opt/rocm}
PYTHON_BIN=${PYTHON_BIN:-python3}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

command -v "$PYTHON_BIN" >/dev/null || fail "Python is not available: $PYTHON_BIN"
test -x "$ROCM_ROOT/lib/llvm/bin/clang++" || fail "ROCm clang++ not found under $ROCM_ROOT"
test -d "$ROCM_ROOT/include" || fail "ROCm headers not found under $ROCM_ROOT"

printf 'ROCm root: %s\n' "$ROCM_ROOT"
"$ROCM_ROOT/lib/llvm/bin/clang++" --version | head -n 1

if command -v rocminfo >/dev/null; then
  rocminfo | awk '/Name: +gfx/{print; found=1} END{exit found ? 0 : 1}' \
    || fail "rocminfo did not report an AMD GPU architecture"
else
  printf 'WARN: rocminfo is unavailable; PyTorch will perform the device gate.\n'
fi

"$PYTHON_BIN" - <<'PY'
import sys
try:
    import torch
except Exception as exc:
    raise SystemExit(f"ERROR: import torch failed: {exc}")
print("Python", sys.version.split()[0])
print("Torch", torch.__version__)
print("HIP", torch.version.hip)
if torch.version.hip is None:
    raise SystemExit("ERROR: this is not a ROCm-enabled PyTorch build")
if not torch.cuda.is_available():
    raise SystemExit("ERROR: PyTorch cannot see the AMD GPU")
print("Device", torch.cuda.get_device_name(0))
print("Capability", torch.cuda.get_device_capability(0))
PY
