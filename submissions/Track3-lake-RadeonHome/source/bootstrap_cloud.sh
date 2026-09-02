#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/persistent/projects/radeon-home"
REFERENCE_DIR="/persistent/projects/reference-franka"
PYTHON_BIN="${RADEONHOME_PYTHON:-/opt/venv/bin/python}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing Python runtime: ${PYTHON_BIN}" >&2
  echo "Set RADEONHOME_PYTHON to the Python executable in this cloud image." >&2
  exit 1
fi

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Missing persistent project: ${PROJECT_DIR}" >&2
  exit 1
fi

if [[ ! -d "${REFERENCE_DIR}/franka_fruit_pick" ]]; then
  echo "Missing Track 3 reference project: ${REFERENCE_DIR}" >&2
  exit 1
fi

export PIP_INDEX_URL
export PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}"

if ! "${PYTHON_BIN}" -c "import genesis" >/dev/null 2>&1; then
  echo "Installing Genesis and the Track 3 reference package..."
  "${PYTHON_BIN}" -m pip install -e "${REFERENCE_DIR}"
fi

# Some Radeon Cloud images bundle scikit-image 0.22 with NumPy 2.x. Importing
# Genesis then fails with "numpy.dtype size changed"; upgrade only when detected.
if ! "${PYTHON_BIN}" -c "import skimage" >/dev/null 2>&1; then
  echo "Repairing the scikit-image / NumPy binary compatibility..."
  "${PYTHON_BIN}" -m pip install --upgrade "scikit-image>=0.25"
fi

"${PYTHON_BIN}" -m pip install -e "${PROJECT_DIR}"

cd "${PROJECT_DIR}"
"${PYTHON_BIN}" -m pytest -q
"${PYTHON_BIN}" - <<'PY'
import genesis
import torch

print(f"Genesis: {genesis.__version__}")
print(f"PyTorch: {torch.__version__}")
print(f"HIP: {torch.version.hip}")
print(f"GPU available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
PY

echo "RadeonHome cloud environment is ready."
