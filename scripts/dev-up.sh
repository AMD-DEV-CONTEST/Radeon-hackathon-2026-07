#!/usr/bin/env bash
# BotverseX local dev launcher — brings up API (8000) + Realtime (8002) with
# the right env vars so that:
#   * /api/setup/health reports lerobot_available: true
#   * /api/runtimes registers `so101`
#   * /api/v1/stats returns non-zero total_frames (HF cache + recording_*)
#
# Usage:
#   bash scripts/dev-up.sh           # start
#   bash scripts/dev-up.sh down      # stop
#   bash scripts/dev-up.sh status    # health probe only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_VENV="$ROOT/apps/api/.venv/bin/python"
RT_VENV="$ROOT/apps/realtime/.venv/bin/python"
API_LOG="/tmp/botversex_api.log"
RT_LOG="/tmp/botversex_realtime.log"

# LeRobot source — where the patched makermods build lives. Override via env
# if you keep it elsewhere.
: "${BOTVERSEX_LEROBOT_PATH:=/media/ethan/8b3b321a-78e4-49ab-a226-08ba4b1de832/home/amd/Downloads/lerobot-MakerMods-main/src}"
export BOTVERSEX_LEROBOT_PATH
export PYTHONPATH="$BOTVERSEX_LEROBOT_PATH:${PYTHONPATH:-}"

# pip / urllib choke on the system-wide socks proxy when it's set without
# pysocks installed, and lerobot upload helpers reach for the network during
# import. Force-clear any proxy vars for the lifetime of these services.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY \
      ALL_PROXY all_proxy SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy

cmd="${1:-up}"

_kill_port() {
  local port="$1"
  local pids
  pids="$(ss -ltnp 2>/dev/null \
    | grep -E ":$port\\b" \
    | grep -oE "pid=[0-9]+" \
    | grep -oE "[0-9]+" \
    | sort -u || true)"
  for pid in $pids; do
    kill "$pid" 2>/dev/null || sudo kill "$pid" 2>/dev/null || true
  done
}

down() {
  echo "[dev-up] stopping API + realtime ..."
  pkill -f "uvicorn app.main:app --port 8000" 2>/dev/null || true
  pkill -f "apps/realtime/run_api.py" 2>/dev/null || true
  _kill_port 8000
  _kill_port 8002
  sleep 1
  echo "[dev-up] stopped."
}

status() {
  echo "== /api/setup/health =="
  curl -sS --noproxy '*' http://127.0.0.1:8002/api/setup/health || true
  echo
  echo "== /api/runtimes =="
  curl -sS --noproxy '*' http://127.0.0.1:8002/api/runtimes || true
  echo
  echo "== /api/v1/auth login (test/test) =="
  TOKEN="$(python3 - <<'PY' 2>/dev/null || true
import json, urllib.request
try:
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/login",
        data=json.dumps({"email":"test","password":"test"}).encode(),
        headers={"Content-Type":"application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        print(json.loads(r.read().decode())["access_token"])
except Exception:
    pass
PY
)"
  if [ -n "$TOKEN" ]; then
    echo "token ok (length=${#TOKEN})"
    echo "== /api/v1/stats =="
    curl -sS --noproxy '*' "http://127.0.0.1:8000/api/v1/stats" -H "Authorization: Bearer $TOKEN"
    echo
  else
    echo "login failed — API may still be starting"
  fi
}

up() {
  if [ ! -x "$API_VENV" ]; then
    echo "[dev-up] missing $API_VENV — run: python3 -m venv apps/api/.venv && pip install -r apps/api/requirements.txt"
    exit 1
  fi
  if [ ! -x "$RT_VENV" ]; then
    echo "[dev-up] missing $RT_VENV — run: python3 -m venv apps/realtime/.venv && pip install -r apps/realtime/requirements.txt"
    exit 1
  fi
  if [ ! -d "$BOTVERSEX_LEROBOT_PATH" ]; then
    echo "[dev-up] WARNING: BOTVERSEX_LEROBOT_PATH=$BOTVERSEX_LEROBOT_PATH does not exist — so101 will not register"
  fi

  down

  echo "[dev-up] starting API (8000) -> $API_LOG"
  (
    cd "$ROOT/apps/api"
    nohup "$API_VENV" -m uvicorn app.main:app --port 8000 --app-dir . \
        >"$API_LOG" 2>&1 &
    disown || true
  )

  echo "[dev-up] starting realtime (8002, HTTP) -> $RT_LOG"
  nohup "$RT_VENV" "$ROOT/apps/realtime/run_api.py" --http \
        >"$RT_LOG" 2>&1 &
  disown || true

  echo "[dev-up] waiting up to 20s for both endpoints ..."
  for i in $(seq 1 20); do
    sleep 1
    api_ok=0; rt_ok=0
    curl -sS --noproxy '*' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health 2>/dev/null \
      | grep -q '^2' && api_ok=1
    curl -sS --noproxy '*' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8002/api/setup/health 2>/dev/null \
      | grep -q '^2' && rt_ok=1
    if [ "$api_ok$rt_ok" = "11" ]; then
      echo "[dev-up] both up after ${i}s"
      break
    fi
  done

  status
}

case "$cmd" in
  up)     up ;;
  down)   down ;;
  status) status ;;
  *)      echo "usage: $0 [up|down|status]"; exit 2 ;;
esac
