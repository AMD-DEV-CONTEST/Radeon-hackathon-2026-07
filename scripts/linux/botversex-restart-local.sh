#!/usr/bin/env bash
# Restart BotverseX on THIS Linux machine (web :5173 + api :8000 + realtime :8002).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="${TMPDIR:-/tmp}"
notify() { notify-send "BotverseX 本机" "$1" 2>/dev/null || true; }

notify "正在重启本机服务…"

# Kill old processes (best-effort)
# The actual process argv is usually just ".venv/bin/python run_api.py --http"
# (its cwd is apps/realtime), so the old pattern missed it and left a stale
# Local Agent bound to :8002.
pkill -f "[r]un_api.py --http" 2>/dev/null || true
pkill -f "uvicorn app.main:app --port 8000" 2>/dev/null || true
# Only kill the botversex vite, not other vite projects
pkill -f "botversex/apps/web.*vite" 2>/dev/null || true
pkill -f "apps/web/node_modules/.bin/vite" 2>/dev/null || true
sleep 1

# Realtime Local Agent (must be --http for Vite proxy)
(
  cd "$ROOT/apps/realtime"
  if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
  setsid nohup "$PY" run_api.py --http >"$LOG_DIR/botversex_realtime.log" 2>&1 </dev/null &
)

# Cloud API
(
  cd "$ROOT/apps/api"
  if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
  setsid nohup "$PY" -m uvicorn app.main:app --port 8000 --app-dir . >"$LOG_DIR/botversex_api.log" 2>&1 </dev/null &
)

# Web (Vite)
(
  cd "$ROOT/apps/web"
  setsid nohup npm run dev -- --host 0.0.0.0 --port 5173 >"$LOG_DIR/botversex_web.log" 2>&1 </dev/null &
)

# Wait and probe
ok=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  sleep 1
  w=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5173/ 2>/dev/null || echo 000)
  a=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/api/setup/health 2>/dev/null || echo 000)
  if [ "$w" = "200" ] && [ "$a" = "200" ]; then ok=1; break; fi
done

LAN=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ "$ok" = "1" ]; then
  notify "已就绪 · 打开 http://127.0.0.1:5173 或 http://${LAN}:5173"
  # Try open browser
  xdg-open "http://127.0.0.1:5173/robots" 2>/dev/null || true
else
  notify "启动可能未完成，请看日志 /tmp/botversex_*.log"
fi

echo "Web:      http://127.0.0.1:5173"
echo "LAN:      http://${LAN}:5173"
echo "Agent:    http://127.0.0.1:8002"
echo "API:      http://127.0.0.1:8000"
echo "Logs:     $LOG_DIR/botversex_{web,api,realtime}.log"
