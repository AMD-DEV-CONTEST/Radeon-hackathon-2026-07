#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/opt/venv/bin/python}"
PERSISTENT_PYTHON_PACKAGES="${PERSISTENT_PYTHON_PACKAGES:-/persistent/python-packages}"

export PYTHONPATH="$PERSISTENT_PYTHON_PACKAGES${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" "$@"
