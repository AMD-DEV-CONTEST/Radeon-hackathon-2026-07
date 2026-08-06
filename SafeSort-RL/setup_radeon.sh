#!/usr/bin/env bash
# SafeSort-RL AMD Radeon / ROCm environment setup
#
# Usage:
#   cd /workspace
#   source ./setup_radeon.sh
#
# This script does not reinstall PyTorch or Genesis. It activates the
# already-configured ROCm environment and verifies the required stack.

set -eo pipefail

PROJECT_DIR="${SAFESORT_PROJECT_DIR:-/workspace}"
VENV_DIR="${SAFESORT_VENV:-/workspace/genesis-clean}"

fail() {
    echo "ERROR: $*" >&2
    return 1 2>/dev/null || exit 1
}

if [[ ! -d "${PROJECT_DIR}" ]]; then
    fail "Project directory does not exist: ${PROJECT_DIR}"
fi

if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
    fail "ROCm Python environment was not found at ${VENV_DIR}"
fi

cd "${PROJECT_DIR}"
source "${VENV_DIR}/bin/activate"

# Select the first visible AMD GPU. PyTorch ROCm exposes it through the
# torch.cuda-compatible API.
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export ROCR_VISIBLE_DEVICES="${ROCR_VISIBLE_DEVICES:-0}"
export PYTHONUNBUFFERED=1

# Folders used by the final notebook.
mkdir -p models/checkpoints logs results videos

echo "SafeSort-RL ROCm environment activated"
echo "  Project: ${PROJECT_DIR}"
echo "  Python environment: ${VENV_DIR}"
echo

python - <<'PY'
import importlib.metadata
import sys

import cv2
import genesis as gs
import gymnasium
import imageio
import numpy as np
import torch

print("Environment verification")
print("  Python executable:", sys.executable)
print("  Python:", sys.version.split()[0])
print("  PyTorch:", torch.__version__)
print("  HIP:", torch.version.hip)
print("  GPU available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("  GPU:", torch.cuda.get_device_name(0))
else:
    print("  GPU: unavailable")

print("  Genesis:", gs.__version__)
print(
    "  Stable-Baselines3:",
    importlib.metadata.version("stable-baselines3"),
)
print("  Gymnasium:", gymnasium.__version__)
print("  NumPy:", np.__version__)
print("  OpenCV:", cv2.__version__)
print("  ImageIO:", imageio.__version__)

assert torch.cuda.is_available(), "ROCm GPU is not available."
assert torch.version.hip is not None, "PyTorch is not a ROCm/HIP build."
assert gs.__version__.startswith("1.3.1"), (
    f"Expected Genesis 1.3.1, found {gs.__version__}"
)

print()
print("Verification passed: AMD ROCm and Genesis are ready.")
PY

echo
echo "Use the Jupyter kernel backed by:"
echo "  ${VENV_DIR}/bin/python"
