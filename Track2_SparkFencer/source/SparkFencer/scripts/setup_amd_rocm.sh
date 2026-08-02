#!/usr/bin/env bash
# Install SparkFencer on a Linux host with a ROCm-supported AMD Radeon GPU.
# PyTorch index versions vary by ROCm release: set PYTORCH_ROCM_INDEX to the
# wheel index that matches the installed ROCm stack, e.g. https://download.pytorch.org/whl/rocm7.2
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
PYTORCH_ROCM_INDEX="${PYTORCH_ROCM_INDEX:-https://download.pytorch.org/whl/rocm7.2}"

if ! command -v rocminfo >/dev/null 2>&1; then
  echo "ERROR: rocminfo was not found. Install a compatible ROCm runtime/driver first." >&2
  exit 1
fi

rocminfo | sed -n '1,20p'
"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip wheel
if [ "${PYTORCH_ROCM_INDEX}" = "https://download.pytorch.org/whl/rocm7.2" ]; then
  "${VENV_DIR}/bin/python" -m pip install -r requirements-rocm.txt
else
  # A different ROCm release was selected by the operator; use matching wheels.
  "${VENV_DIR}/bin/python" -m pip install torch torchvision --index-url "${PYTORCH_ROCM_INDEX}"
fi
"${VENV_DIR}/bin/python" -m pip install -r requirements.txt -r requirements-webui.txt

"${VENV_DIR}/bin/python" - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda_api_available:", torch.cuda.is_available())
print("hip_version:", torch.version.hip)
if not torch.cuda.is_available() or not torch.version.hip:
    raise SystemExit("ROCm PyTorch validation failed")
print("gpu:", torch.cuda.get_device_name(0))
PY

echo "ROCm environment ready. Next: ${VENV_DIR}/bin/python scripts/build_knowledge.py"
