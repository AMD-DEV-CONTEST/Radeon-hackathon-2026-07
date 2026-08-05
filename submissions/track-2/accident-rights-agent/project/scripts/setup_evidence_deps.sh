#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
PERSISTENT_PYTHON_PACKAGES="${PERSISTENT_PYTHON_PACKAGES:-/persistent/python-packages}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

mkdir -p "$PERSISTENT_PYTHON_PACKAGES"
"$PYTHON_BIN" -m pip install \
  --upgrade \
  --index-url "$PIP_INDEX_URL" \
  --target "$PERSISTENT_PYTHON_PACKAGES" \
  "PyMuPDF>=1.26,<2"

PYTHONPATH="$PERSISTENT_PYTHON_PACKAGES${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" -c \
  'import fitz; print("PyMuPDF", getattr(fitz, "__version__", "unknown"))'
