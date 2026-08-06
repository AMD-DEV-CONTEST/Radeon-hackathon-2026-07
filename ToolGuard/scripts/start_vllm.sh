#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR" || exit 1
source "$PROJECT_DIR/setup_env.sh"
SESSION="vllm"
if tmux has-session -t $SESSION 2>/dev/null; then
    if [ -n "$TMUX" ]; then
        echo "[start_vllm] Session '$SESSION' already running. Switching to it..."
        tmux switch-client -t $SESSION
    else
        echo "[start_vllm] Session '$SESSION' already running. Attaching..."
        tmux attach -t $SESSION
    fi
else
    echo "[start_vllm] Starting new vLLM session (with correct persistent cache paths)..."
    tmux new-session -d -s $SESSION \
      "export HF_HUB_CACHE='$HF_HUB_CACHE'; export VLLM_CACHE_ROOT='$VLLM_CACHE_ROOT'; export PATH='$PATH'; /opt/venv/bin/vllm serve Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0 --port 8000 --enable-auto-tool-choice --tool-call-parser hermes"
    echo "[start_vllm] Started in background. Attach anytime with: tmux attach -t $SESSION"
    echo "[start_vllm] Detach without stopping it: Ctrl+B then D"
fi
