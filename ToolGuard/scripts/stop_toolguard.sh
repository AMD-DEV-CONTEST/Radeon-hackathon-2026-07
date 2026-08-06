#!/bin/bash
echo "[stop_toolguard] Stopping dashboard..."
pkill -f terminal_dashboard.py 2>/dev/null

echo "[stop_toolguard] Stopping live agent loop..."
tmux kill-session -t toolguard_agent 2>/dev/null

echo "[stop_toolguard] Stopping model server..."
tmux kill-session -t vllm 2>/dev/null

echo "[stop_toolguard] All stopped."
