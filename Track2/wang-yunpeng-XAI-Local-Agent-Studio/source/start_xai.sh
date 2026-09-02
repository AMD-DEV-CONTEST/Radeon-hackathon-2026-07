#!/bin/bash
# XAI 后端进程守护启动器
set -u
PROJECT_DIR="/Users/Admin/Desktop/mask/xai"
PYTHON="/Users/Admin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
LOG="/tmp/xai_server.log"
WRAPPER_PIDFILE="$PROJECT_DIR/.xai_server_wrapper.pid"
echo $$ > "$WRAPPER_PIDFILE"
cd "$PROJECT_DIR" || exit 1
while true; do
  COMMIT=$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
  echo "[wrapper $(date '+%F %T')] starting xai server (commit: $COMMIT)" >> "$LOG"
  XAI_HOST=localhost XAI_PORT=8000 XAI_HOME="$HOME/.xai" XAI_COMMIT="$COMMIT" \
    "$PYTHON" "$PROJECT_DIR/server_xai.py" >> "$LOG" 2>&1
  RC=$?
  echo "[wrapper $(date '+%F %T')] server exited (rc=$RC), restart in 2s..." >> "$LOG"
  sleep 2
done
