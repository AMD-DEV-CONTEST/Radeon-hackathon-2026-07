#!/usr/bin/env bash
# Install project dependencies into the AMD competition image's prebuilt venv.
# This intentionally preserves the ROCm-enabled PyTorch shipped by the image.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: expected the competition image Python at $PYTHON_BIN" >&2
  echo "Set PYTHON_BIN to the interpreter containing the preinstalled ROCm PyTorch." >&2
  exit 1
fi

# Genesis creates an off-screen rasterizer even when no GUI viewer is opened.
# Minimal cloud images frequently omit the EGL/Mesa loader needed by PyOpenGL.
if command -v apt-get >/dev/null 2>&1 && [[ "$(id -u)" == "0" ]]; then
  apt-get update
  apt-get install -y --no-install-recommends libegl1 libegl-mesa0 libgl1 libgl1-mesa-dri
fi
export PYOPENGL_PLATFORM="${PYOPENGL_PLATFORM:-egl}"

# A local proxy from a developer workstation is invalid inside the cloud VM.
for proxy_var in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy PIP_PROXY; do
  proxy_value="${!proxy_var:-}"
  if [[ "$proxy_value" == *"127.0.0.1:7890"* ]]; then
    unset "$proxy_var"
    echo "Unset stale $proxy_var proxy setting."
  fi
done

TORCH_CONSTRAINT="$(mktemp)"
trap 'rm -f "$TORCH_CONSTRAINT"' EXIT

"$PYTHON_BIN" - "$TORCH_CONSTRAINT" <<'PY'
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import torch

print(f"Python: {sys.executable}")
print(f"PyTorch: {torch.__version__}")
print(f"HIP: {torch.version.hip}")
print(f"GPU available: {torch.cuda.is_available()}")
if torch.version.hip is None or not torch.cuda.is_available():
    raise SystemExit(
        "ERROR: this interpreter does not expose a usable ROCm PyTorch GPU. "
        "Do not install project dependencies until the competition image is fixed."
    )

constraints = [f"torch=={torch.__version__}"]
# Several Genesis rendering dependencies still publish extension wheels built
# against NumPy 1.x. Pinning the ABI avoids importing an old scikit-image wheel
# with NumPy 2.x ("numpy.dtype size changed").
constraints.append("numpy<2")
for package in ("torchvision", "torchaudio"):
    try:
        package_version = version(package)
    except PackageNotFoundError:
        continue
    constraints.append(f"{package}=={package_version}")
Path(sys.argv[1]).write_text("\n".join(constraints) + "\n")
PY

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install --no-cache-dir --force-reinstall --constraint "$TORCH_CONSTRAINT" \
  "numpy<2" scipy scikit-image
"$PYTHON_BIN" -m pip install --constraint "$TORCH_CONSTRAINT" \
  "genesis-world[render]" \
  cleanrl onnx opencv-python gymnasium tensorboard pyyaml tqdm scipy scikit-image pytest h5py

"$PYTHON_BIN" "$PROJECT_ROOT/tests/test_gpu.py"
echo "Setup complete. Use: source /opt/venv/bin/activate"
