#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_LOG="/tmp/botversex_web.log"

cmd="${1:-up}"

up() {
  echo "[dev-all] starting API + realtime ..."
  bash "$ROOT/scripts/dev-up.sh" up

  echo "[dev-all] starting web (5173) -> $WEB_LOG"
  pkill -f "apps/web.*vite" 2>/dev/null || true
  pkill -f "npm run dev -- --host 0.0.0.0" 2>/dev/null || true
  nohup npm --prefix "$ROOT/apps/web" run dev -- --host 0.0.0.0 \
    >"$WEB_LOG" 2>&1 &
  disown || true

  echo "[dev-all] waiting for web health ..."
  for i in $(seq 1 20); do
    sleep 1
    if curl -sS --noproxy '*' -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:5173" 2>/dev/null | grep -Eq '^2'; then
      echo "[dev-all] web up after ${i}s"
      break
    fi
  done

  status
}

down() {
  echo "[dev-all] stopping web + API + realtime ..."
  pkill -f "apps/web.*vite" 2>/dev/null || true
  pkill -f "npm run dev -- --host 0.0.0.0" 2>/dev/null || true
  bash "$ROOT/scripts/dev-up.sh" down
  echo "[dev-all] stopped."
}

status() {
  echo "== web =="
  curl -sS --noproxy '*' "http://127.0.0.1:5173" >/dev/null \
    && echo "web: up (http://127.0.0.1:5173)" \
    || echo "web: down"
  echo
  bash "$ROOT/scripts/dev-up.sh" status
}

case "$cmd" in
  up) up ;;
  down) down ;;
  status) status ;;
  *) echo "usage: $0 [up|down|status]"; exit 2 ;;
esac
