#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APT_CACHE="/persistent/apt_cache"
PIP_CACHE="/persistent/pip_cache"

mkdir -p "$APT_CACHE" "$PIP_CACHE"

echo "[bootstrap] Checking system packages (ca-certificates, tmux)..."
if command -v tmux >/dev/null 2>&1 && [ -f /etc/ssl/certs/ca-certificates.crt ]; then
    echo "[bootstrap] Already present. Skipping."
else
    if ls "$APT_CACHE"/*.deb >/dev/null 2>&1; then
        echo "[bootstrap] Installing from cache, no internet needed..."
        dpkg -i "$APT_CACHE"/*.deb || apt-get install -f -y -qq
    else
        echo "[bootstrap] Downloading once (first time only)..."
        apt update -qq
        apt install -y -qq --download-only -o Dir::Cache::Archives="$APT_CACHE" ca-certificates tmux
        apt install -y -qq ca-certificates tmux
    fi
    update-ca-certificates
fi

echo "[bootstrap] Installing Python dependencies from requirements.txt..."
if [ -d "$PIP_CACHE" ] && [ "$(ls -A "$PIP_CACHE" 2>/dev/null)" ]; then
    /opt/venv/bin/pip install --no-index --find-links="$PIP_CACHE" -r "$PROJECT_DIR/requirements.txt" \
      || /opt/venv/bin/pip install -r "$PROJECT_DIR/requirements.txt"
else
    /opt/venv/bin/pip download -r "$PROJECT_DIR/requirements.txt" -d "$PIP_CACHE"
    /opt/venv/bin/pip install -r "$PROJECT_DIR/requirements.txt"
fi

echo "[bootstrap] Loading environment variables..."
source "$PROJECT_DIR/setup_env.sh"

echo ""
echo "[bootstrap] Environment ready. Next: scripts/start_vllm.sh"
echo "[bootstrap] (To push changes to GitHub, run: source /persistent/restore_ssh.sh)"
