#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVIDER="${ALPHANOAH_PROVIDER:-ollama}"
MODEL="${ALPHANOAH_MODEL:-qwen3.5:9b}"
API_PORT="${ALPHANOAH_API_PORT:-8090}"
FRONTEND_PORT="${ALPHANOAH_FRONTEND_PORT:-5173}"
DATABASE="${ALPHANOAH_DATABASE:-$ROOT_DIR/tmp/alphanoah_web_api.sqlite3}"

case "$PROVIDER" in fake|ollama) ;; *) echo "ALPHANOAH_PROVIDER must be fake or ollama."; exit 2;; esac
command -v python3 >/dev/null || { echo "Python 3 is required."; exit 1; }
command -v npm >/dev/null || { echo "npm is required."; exit 1; }
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then "$ROOT_DIR/install.sh"; fi
if [[ "$PROVIDER" == "ollama" ]]; then
  command -v ollama >/dev/null || { echo "Ollama is required for ALPHANOAH_PROVIDER=ollama."; exit 1; }
  ollama list | awk 'NR>1 {print $1}' | grep -Fx "$MODEL" >/dev/null || { echo "Ollama model $MODEL is not installed."; exit 1; }
fi
mkdir -p "$ROOT_DIR/tmp"
backend=(python3 -m alphanoah_a1.web_api --db "$DATABASE" --port "$API_PORT" --provider "$PROVIDER")
if [[ "$PROVIDER" == "ollama" ]]; then backend+=(--model "$MODEL"); fi
cleanup(){ kill "${API_PID:-}" "${UI_PID:-}" 2>/dev/null || true; wait "${API_PID:-}" "${UI_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
(cd "$ROOT_DIR" && PYTHONPATH=src "${backend[@]}") &
API_PID=$!
(cd "$ROOT_DIR/frontend" && npm run dev -- --port "$FRONTEND_PORT") &
UI_PID=$!
for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 0.25
done
curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null || { echo "Web API failed to start."; exit 1; }
cat <<OUT

AlphaNoah A1 Edge Agent

Runtime: RUNNING
Web API: RUNNING
Frontend: RUNNING

Provider: ${PROVIDER^}
Model: $([[ "$PROVIDER" == "ollama" ]] && echo "$MODEL" || echo "synthetic")

Frontend:
http://127.0.0.1:$FRONTEND_PORT

API:
http://127.0.0.1:$API_PORT
OUT
wait "$API_PID" "$UI_PID"
