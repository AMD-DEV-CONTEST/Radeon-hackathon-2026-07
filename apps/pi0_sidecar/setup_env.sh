#!/usr/bin/env bash
# Plan B setup: create a dedicated Python 3.12 venv for Pi0 inference.
#
# Intentionally does NOT touch apps/realtime/.venv or anything ROCm-related.
# Uses `uv` (installed locally into apps/pi0_sidecar/.bin) to build the venv,
# so it works even when python3.12-venv / ensurepip aren't apt-installed.
#
# Re-running this script is idempotent.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${HERE}/.venv"
UV_BIN_DIR="${HERE}/.bin"
UV="${UV_BIN_DIR}/uv"

echo "[pi0_sidecar] setup_env.sh"
echo "[pi0_sidecar] target venv: ${VENV}"

# The ROCm LD_PRELOAD will complain in a pure-python 3.12 context; strip it.
unset LD_PRELOAD

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "ERROR: python3.12 not found in PATH." >&2
  echo "       Install it (Ubuntu): sudo apt install python3.12" >&2
  exit 1
fi

# Pre-flight: lerobot -> pynput -> evdev requires Python headers and a C
# toolchain. Failing fast here saves ~10 minutes of download + resolve time.
PY_INCLUDE_DIR="$(python3.12 -c 'import sysconfig; print(sysconfig.get_path("include"))' 2>/dev/null || true)"
if [ -z "${PY_INCLUDE_DIR}" ] || [ ! -f "${PY_INCLUDE_DIR}/Python.h" ]; then
  echo "ERROR: Python.h not found for python3.12 (expected under ${PY_INCLUDE_DIR:-<unknown>})." >&2
  echo "       evdev (pulled in by lerobot -> pynput) needs to compile a C extension." >&2
  echo "       Ubuntu/Debian fix:" >&2
  echo "         sudo apt install -y python3.12-dev build-essential" >&2
  exit 1
fi
if ! command -v gcc >/dev/null 2>&1 && ! command -v cc >/dev/null 2>&1; then
  echo "ERROR: no C compiler (gcc/cc) on PATH; evdev will fail to build." >&2
  echo "       Fix: sudo apt install -y build-essential" >&2
  exit 1
fi

# --- 1. bootstrap uv locally (no sudo) -------------------------------------
if [ ! -x "${UV}" ]; then
  echo "[pi0_sidecar] installing local uv into ${UV_BIN_DIR}"
  mkdir -p "${UV_BIN_DIR}"
  export UV_INSTALL_DIR="${UV_BIN_DIR}"
  export UV_UNMANAGED_INSTALL="${UV_BIN_DIR}"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "ERROR: need curl or wget to fetch uv." >&2
    exit 1
  fi
fi

if [ ! -x "${UV}" ]; then
  # uv installer sometimes drops the binary directly (not in subdir)
  if [ -x "${UV_BIN_DIR}/uv" ]; then
    UV="${UV_BIN_DIR}/uv"
  elif [ -x "${HOME}/.local/bin/uv" ]; then
    UV="${HOME}/.local/bin/uv"
  else
    echo "ERROR: uv install did not produce a binary at ${UV}" >&2
    exit 1
  fi
fi

echo "[pi0_sidecar] uv version: $("${UV}" --version)"

# --- 2. create the venv with uv --------------------------------------------
if [ ! -d "${VENV}" ]; then
  echo "[pi0_sidecar] creating venv with uv (python 3.12)"
  "${UV}" venv --python python3.12 "${VENV}"
else
  echo "[pi0_sidecar] venv already exists, reusing"
fi

# --- 3. install dependencies -----------------------------------------------
echo "[pi0_sidecar] installing dependencies (this can take a few minutes)..."
VIRTUAL_ENV="${VENV}" "${UV}" pip install --upgrade pip setuptools wheel
VIRTUAL_ENV="${VENV}" "${UV}" pip install -r "${HERE}/requirements.txt"

# uv's resolver will sometimes prefer a newer ``lerobot`` snapshot built from
# git+main (currently 0.5.2-dev) over the pinned PyPI wheel, and that snapshot
# ships a broken ``lerobot/utils/__init__.py`` (missing DEFAULT_FEATURES,
# IMAGENET_STATS, require_package). Force the stable 0.5.1 PyPI wheel and
# block its transitive upgrades.
echo "[pi0_sidecar] pinning lerobot to 0.5.1 PyPI wheel (avoids broken git+main 0.5.2)"
"${VENV}/bin/pip" install --no-deps --force-reinstall "lerobot[pi]==0.5.1"

# --- 4. smoke-test LeRobot policy imports ----------------------------------
echo "[pi0_sidecar] verifying LeRobot ACT + Pi0 imports..."
"${VENV}/bin/python" - <<'PY'
import importlib
mods = ["torch", "transformers", "lerobot", "fastapi", "uvicorn"]
for m in mods:
    importlib.import_module(m)
    print(f"  import {m}: OK")
from lerobot.policies.pi0 import PI0Policy  # noqa: F401
from lerobot.policies.act.modeling_act import ACTPolicy  # noqa: F401
print("  import PI0Policy, ACTPolicy: OK")
PY

echo "[pi0_sidecar] done. Next: bash apps/pi0_sidecar/run.sh"
