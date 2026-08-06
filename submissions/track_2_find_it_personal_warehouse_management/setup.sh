#!/usr/bin/env bash
# setup.sh — prepare the Find it environment.
#
# Recommended Python: 3.10+ (developed against 3.11 / 3.12).
# Uses uv for fast installs; the project venv lives at ./.venv.
# Override VENV_DIR to use another env.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$HERE/.venv}"

echo "==> Checking system dependencies (ffmpeg / ffprobe / uv)"
if ! command -v ffprobe >/dev/null 2>&1; then
  echo "ERROR: ffprobe not found. Install ffmpeg first, e.g.:"
  echo "    sudo apt-get install -y ffmpeg"
  exit 1
fi
ffprobe -version | head -1

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not found. Install it first:"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

echo "==> Using virtualenv: $VENV_DIR"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "    venv not found — creating with uv (python 3.11+)"
  uv venv "$VENV_DIR" --python 3.11
fi

echo "==> Python version"
"$VENV_DIR/bin/python" --version

echo "==> Installing Python dependencies"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
uv pip install -r "$HERE/requirements.txt"

mkdir -p "$HERE/uploads"

echo
echo "Setup complete. Launch with:  $HERE/launch.sh"
