#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_config
if is_running; then echo "AlphaNoah is already running (PID $(<"$PID_FILE"))."; exit 0; fi
[[ -x "$PACKAGE_ROOT/.venv/bin/python" ]] || { echo "Run ./scripts/install.sh first."; exit 2; }
[[ "$ALPHANOAH_PORT" =~ ^[0-9]+$ ]] || { echo "Invalid port."; exit 2; }
if ! "$PACKAGE_ROOT/.venv/bin/python" - "$ALPHANOAH_PORT" <<\PY
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try: s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError: raise SystemExit(1)
finally: s.close()
PY
then
  echo "Port $ALPHANOAH_PORT is already in use; AlphaNoah was not started."
  exit 1
fi
mkdir -p "$PACKAGE_ROOT/data" "$PACKAGE_ROOT/logs"
args=(--db "$PACKAGE_ROOT/data/alphanoah.sqlite3" --port "$ALPHANOAH_PORT" --static-dir "$PACKAGE_ROOT/app/frontend" --provider "$ALPHANOAH_PROVIDER")
case "$ALPHANOAH_PROVIDER" in
 fake) ;;
 ollama) args+=(--model "$ALPHANOAH_MODEL" --base-url "$ALPHANOAH_BASE_URL") ;;
 openai_compatible)
   export ALPHANOAH_LOCAL_API_KEY="$ALPHANOAH_API_KEY"
   args+=(--model "$ALPHANOAH_MODEL" --base-url "$ALPHANOAH_BASE_URL" --credential-env ALPHANOAH_LOCAL_API_KEY)
   ;;
 *) echo "Unsupported provider configuration."; exit 2 ;;
esac
nohup env PYTHONPATH="$PACKAGE_ROOT/app/backend/src" "$PACKAGE_ROOT/.venv/bin/python" -m alphanoah_a1.web_api "${args[@]}" >>"$LOG_FILE" 2>&1 &
pid=$!; printf "%s\n" "$pid" > "$PID_FILE"
for _ in {1..40}; do
  kill -0 "$pid" 2>/dev/null || break
  curl -fsS "http://127.0.0.1:$ALPHANOAH_PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.25
done
if ! curl -fsS "http://127.0.0.1:$ALPHANOAH_PORT/api/health" >/dev/null; then kill "$pid" 2>/dev/null || true; rm -f "$PID_FILE"; echo "AlphaNoah failed to start. See logs/alphanoah.log"; exit 1; fi
cat <<TXT
AlphaNoah A1 Edge Agent

Status: RUNNING
Deployment: Local Edge
Provider: $ALPHANOAH_PROVIDER
Model: ${ALPHANOAH_MODEL:-synthetic}
Inference: $ALPHANOAH_INFERENCE_SCOPE
Database: Local SQLite
Frontend: http://127.0.0.1:$ALPHANOAH_PORT
TXT
