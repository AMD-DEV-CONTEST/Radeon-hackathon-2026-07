#!/usr/bin/env bash
# Live-Science one-command public deploy (Radeon Cloud Notebook)
# Prerequisite: the notebook must be a newly created Pod (with FRP_BROKER_URL).
# Usage: bash web/deploy-public.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/web/backend"
FRONTEND="$ROOT/web/frontend"
PORT="${LIVE_SCIENCE_PORT:-8000}"
LOG_DIR="${LIVE_SCIENCE_LOG_DIR:-/tmp/live-science}"
mkdir -p "$LOG_DIR"

echo "==> [1/5] Python environment (create .venv and install deps if missing)"
PY="${LIVE_SCIENCE_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  echo "    creating virtualenv .venv ..."
  python3 -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
  "$PY" -m pip install --upgrade pip -q
  echo "    installing Python deps (incl. manim, may take minutes) ..."
  "$PY" -m pip install -r "$BACKEND/requirements.txt"
fi
"$PY" --version

echo "==> [2/5] Frontend build (rebuild if node is available, else use committed dist)"
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  (cd "$FRONTEND" && npm install --no-audit --no-fund >/dev/null && npm run build)
else
  echo "    node/npm not found -> using committed web/frontend/dist"
  [ -d "$FRONTEND/dist" ] || { echo "ERROR: no dist and no node; cannot build the frontend" >&2; exit 1; }
fi

echo "==> [3/5] Start the backend (auth + frontend hosting, port $PORT)"
pkill -f '[u]vicorn app.main:app' 2>/dev/null || true
sleep 1
(
  cd "$BACKEND"
  LIVE_SCIENCE_SERVE_FRONTEND=1 LIVE_SCIENCE_HOST=0.0.0.0 LIVE_SCIENCE_PORT="$PORT" \
    nohup "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
    > "$LOG_DIR/backend.log" 2>&1 &
)
for i in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/" >/dev/null 2>&1 && break
  sleep 0.5
done
TOKEN="$(cat "$BACKEND/data/auth_token.txt" 2>/dev/null || true)"
echo "    access token: ${TOKEN:-see $LOG_DIR/backend.log}"

echo "==> [4/5] Install rc-tunnel (if not installed)"
if [ ! -x "$HOME/.local/bin/rc-tunnel" ]; then
  /var/run/secrets/frp-self-service/install
fi
"$HOME/.local/bin/rc-tunnel" version >/dev/null 2>&1 || {
  echo "rc-tunnel install failed: make sure this is a new Notebook Pod (env | grep FRP_BROKER_URL should print something)." >&2
  exit 1
}

echo "==> [5/5] Expose public port $PORT"
nohup "$HOME/.local/bin/rc-tunnel" expose --port "$PORT" > "$LOG_DIR/tunnel.log" 2>&1 &
TPID=$!
for i in $(seq 1 30); do
  grep -qEo 'https://rc-[a-z0-9]+\.radeon\.firstdg\.ai' "$LOG_DIR/tunnel.log" 2>/dev/null && break
  sleep 1
done
sleep 3
echo "    rc-tunnel PID: $TPID"
cat "$LOG_DIR/tunnel.log"
echo
echo "================= Deploy complete ================="
echo "Public URL: $(grep -Eo 'https://rc-[a-z0-9]+\.radeon\.firstdg\.ai' "$LOG_DIR/tunnel.log" | head -1 || echo 'see tunnel.log')"
echo "Local URL:  http://127.0.0.1:$PORT"
echo "Access token: ${TOKEN:-see $LOG_DIR/backend.log} (needed on the login page)"
