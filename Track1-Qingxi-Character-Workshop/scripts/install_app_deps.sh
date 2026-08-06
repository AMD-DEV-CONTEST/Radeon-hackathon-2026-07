#!/usr/bin/env bash
# Safe app dependency install for AMD ROCm.
# NEVER run plain "pip install torch" from default/Tsinghua PyPI.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> [1/3] Preflight: torch must already be ROCm-capable"
python3 - <<'PY'
import sys
try:
    import torch
except ImportError:
    print("FAIL: torch not installed. Install ROCm torch FIRST (see docs).")
    sys.exit(1)
ver = torch.__version__
ok = torch.cuda.is_available()
hip = getattr(torch.version, "hip", None)
print(f"torch={ver} cuda_available={ok} hip={hip}")
if not ok:
    print("FAIL: torch.cuda.is_available() is False. Fix ROCm torch before app deps.")
    sys.exit(2)
if "cu" in ver and "rocm" not in ver.lower():
    print("FAIL: looks like NVIDIA CUDA wheel (+cu*). Uninstall and install ROCm torch.")
    sys.exit(3)
print("PREFLIGHT OK")
PY

echo "==> [2/3] Install requirements.txt (no torch line)"
python3 -m pip install -r requirements.txt

echo "==> [3/3] Postflight: torch must STILL be ROCm"
python3 - <<'PY'
import sys
import torch
ver = torch.__version__
ok = torch.cuda.is_available()
hip = getattr(torch.version, "hip", None)
print(f"torch={ver} cuda_available={ok} hip={hip}")
if not ok or ("cu" in ver and "rocm" not in ver.lower()):
    print("FAIL: torch was overwritten or broken. Reinstall ROCm torch.")
    sys.exit(4)
print("INSTALL APP DEPS OK")
PY
