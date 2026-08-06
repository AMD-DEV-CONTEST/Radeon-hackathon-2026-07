#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

source setup_env.sh

echo "[start_toolguard] Starting model server..."
scripts/start_vllm.sh

echo "[start_toolguard] Waiting for the model to be ready..."
until curl -s http://localhost:8000/v1/models > /dev/null 2>&1; do
    sleep 2
done
echo "[start_toolguard] Model is ready."

echo "[start_toolguard] Starting ToolGuard's live detection loop..."
tmux kill-session -t toolguard_agent 2>/dev/null
tmux new-session -d -s toolguard_agent "/opt/venv/bin/python3 agent/live_demo.py"

echo "[start_toolguard] Launching live dashboard..."
sleep 2
/opt/venv/bin/python3 dashboard/terminal_dashboard.py
