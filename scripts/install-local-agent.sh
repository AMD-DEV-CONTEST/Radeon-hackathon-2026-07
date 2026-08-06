#!/usr/bin/env bash
# BotverseX Local Agent — one-shot installer (Linux)
#
# Handles common demo failures:
#   - missing python3-venv / python3-dev
#   - huge CUDA torch download from lerobot
#   - slow PyPI in China (uses Aliyun mirror + CPU torch)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/metahubaifeel/botversex-local-agent/main/scripts/install-linux.sh | bash
#   — or from this monorepo:
#   bash scripts/install-local-agent.sh
#   bash scripts/install-local-agent.sh --dir ~/botversex-local-agent
set -euo pipefail

INSTALL_DIR="${HOME}/botversex-local-agent"
REPO_URL="https://github.com/metahubaifeel/botversex-local-agent.git"
PYPI_MIRROR="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
TORCH_CPU_INDEX="https://download.pytorch.org/whl/cpu"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

need_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo "[error] Missing command: $1"
    return 1
  fi
}

echo "============================================"
echo " BotverseX Local Agent installer"
echo " Install dir: $INSTALL_DIR"
echo "============================================"

if ! need_cmd git || ! need_cmd python3; then
  echo "Install git and python3 first, e.g.:"
  echo "  sudo apt update && sudo apt install -y git python3 python3-venv python3-pip python3-dev build-essential"
  exit 1
fi

if ! python3 -c "import venv" 2>/dev/null; then
  echo "[error] python3-venv is not available."
  echo "  sudo apt install -y python3-venv python3-dev build-essential"
  exit 1
fi

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  echo "[install] Cloning $REPO_URL ..."
  if ! git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"; then
    echo "[error] git clone failed. In China you may need a proxy for GitHub, or use a mirror:"
    echo "  git clone https://gitclone.com/github.com/metahubaifeel/botversex-local-agent.git $INSTALL_DIR"
    exit 1
  fi
else
  echo "[install] Repo exists, pulling latest..."
  git -C "$INSTALL_DIR" pull --ff-only || true
fi

cd "$INSTALL_DIR"

if [[ ! -d .venv ]]; then
  echo "[install] Creating virtualenv..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip -q

echo "[install] Installing CPU PyTorch (avoids ~800MB CUDA download)..."
pip install --retries 5 --timeout 300 \
  "torch>=2.2.0,<2.11.0" "torchvision>=0.17.0,<0.26.0" \
  --index-url "$TORCH_CPU_INDEX"

echo "[install] Installing Local Agent dependencies (PyPI mirror: $PYPI_MIRROR)..."
pip install --retries 5 --timeout 300 \
  -i "$PYPI_MIRROR" --trusted-host mirrors.aliyun.com \
  -r requirements.txt

echo ""
echo "[install] Verifying import..."
python -c "from api.main import app; print('app ok:', app.title)"

echo ""
echo "============================================"
echo " Done. Start the agent:"
echo "   cd $INSTALL_DIR"
echo "   source .venv/bin/activate"
echo "   python run_api.py"
echo ""
echo " Then in your browser (once per machine):"
echo "   1) Open https://localhost:8002 and accept the self-signed certificate"
echo "   2) Verify: https://localhost:8002/api/setup/health"
echo "   3) Open https://botversex.feispace.me/setup and click Refresh"
echo "============================================"
