#!/usr/bin/env bash
set -euo pipefail

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export OLLAMA_KEEP_ALIVE=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DETERMINEX_ROOT="${DETERMINEX_ROOT:-$SCRIPT_DIR}"

echo "=============================================="
echo "[DETERMINEX] BOOTING SYSTEM"
echo "=============================================="

# Resolve Python interpreter
if [ -n "${DETERMINEX_PYTHON:-}" ]; then
    PYTHON="$DETERMINEX_PYTHON"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "[BOOT] ERROR: Python not found. Install Python 3.11+ or set DETERMINEX_PYTHON."
    exit 1
fi

echo "[BOOT] Python: $PYTHON"

# Step 1: Dependency audit
echo "[BOOT] Running dependency audit..."
cd "$DETERMINEX_ROOT"
"$PYTHON" dependency_auditor.py
echo ""

# Step 2: Kill stale processes (Linux/macOS)
echo "[BOOT] Cleaning up stale Determinex processes..."
pkill -f "determinex_hive" 2>/dev/null || true
echo ""

# Step 3: Start Hive backend via Docker (if available)
echo "[BOOT] Checking for Docker..."
if command -v docker &>/dev/null; then
    if docker info &>/dev/null 2>&1; then
        echo "[BOOT] Starting Determinex Hive backend..."
        if docker compose -f "$DETERMINEX_ROOT/docker/docker-compose.hive.yml" up -d --build; then
            echo "[BOOT] Hive container started."
        else
            echo "[BOOT] WARNING: Hive container failed to start. Continuing in local mode."
        fi
    else
        echo "[BOOT] WARNING: Docker is installed but not running."
        echo "[BOOT] Continuing without Hive container (local Ollama only)."
    fi
else
    echo "[BOOT] WARNING: Docker not found. Install Docker for full Hive support."
    echo "[BOOT] Continuing without Hive container (local Ollama only)."
fi
echo ""

# Step 4: Verify Ollama is reachable
echo "[BOOT] Checking Ollama daemon..."
if curl -s -o /dev/null -w "%{http_code}" http://localhost:11434/api/tags 2>/dev/null | grep -q "200"; then
    echo "[BOOT] Ollama is running on port 11434."
else
    echo "[BOOT] WARNING: Ollama not detected on port 11434."
    echo "[BOOT]   Start Ollama and pull a model: ollama pull qwen2.5-coder:7b"
fi
echo ""

# Step 5: Launch Tauri dev build
echo "[BOOT] Launching Determinex via cargo tauri dev..."
cd "$DETERMINEX_ROOT/frontend"
npx tauri dev &

echo ""
echo "=============================================="
echo "[DETERMINEX] Tauri dev build launching."
echo "  The Rust backend compiles first, then"
echo "  Next.js starts on :3000 and the native"
echo "  window opens automatically."
echo "=============================================="
