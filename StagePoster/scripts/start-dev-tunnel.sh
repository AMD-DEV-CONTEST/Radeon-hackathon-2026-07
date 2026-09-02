#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND_ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
  pwd
)"

PROJECT_ROOT="$BACKEND_ROOT"
ENV_FILE="${ENV_FILE:-}"

# Support both backend/.env (legacy) and project root .env
if [[ -z "$ENV_FILE" ]]; then
  if [[ -f "$BACKEND_ROOT/.env" ]]; then
    ENV_FILE="$BACKEND_ROOT/.env"
  elif [[ -f "$PROJECT_ROOT/.env" ]]; then
    ENV_FILE="$PROJECT_ROOT/.env"
  fi
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed." >&2
  echo "Run scripts/install-cloudflared.sh first." >&2
  exit 1
fi

mkdir -p \
  "$BACKEND_ROOT/logs" \
  "$BACKEND_ROOT/run"

PID_FILE="$BACKEND_ROOT/run/cloudflared.pid"
LOG_FILE="$BACKEND_ROOT/logs/cloudflared.log"

if [[ -f "$PID_FILE" ]] &&
  kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Cloudflare Tunnel is already running."
else
  rm -f "$PID_FILE"
  : > "$LOG_FILE"

  nohup cloudflared tunnel \
    --no-autoupdate \
    --url http://127.0.0.1:8080 \
    > "$LOG_FILE" 2>&1 &

  echo $! > "$PID_FILE"
fi

PUBLIC_URL=""

for _ in $(seq 1 60); do
  PUBLIC_URL="$(
    grep -oE \
      'https://[a-zA-Z0-9-]+\.trycloudflare\.com' \
      "$LOG_FILE" \
    | tail -1 \
    || true
  )"

  if [[ -n "$PUBLIC_URL" ]]; then
    break
  fi

  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "cloudflared exited unexpectedly." >&2
    tail -100 "$LOG_FILE" >&2
    exit 1
  fi

  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "Tunnel is running but no public URL was found yet." >&2
  echo "Inspect: $LOG_FILE" >&2
  exit 1
fi

echo "Development public API:"
echo "$PUBLIC_URL"

echo
echo "Testing tunnel..."

curl -i \
  "$PUBLIC_URL/api/ai/sessions/not-found" \
  || true
