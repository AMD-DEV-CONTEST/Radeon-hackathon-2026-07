#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env_local.sh"

cd "$BG_REPO"

CONFIG="configs/competition/app.yaml"
MODEL="$BG_MODELS/llm/qwen3-14b-q8/Qwen3-14B-Q8_0.gguf"
LLAMA_SERVER=$(find "$BG_RUNTIME/llama.cpp" -type f -name 'llama-server' -print -quit 2>/dev/null || true)

echo "=== BuildGuard Radeon startup ==="
echo "Repo:         $BG_REPO"
echo "Venv:         $BG_VENV"
echo "LLM model:    $MODEL"
echo "llama-server: ${LLAMA_SERVER:-NOT FOUND}"

# ── Preflight ─────────────────────────────────────────────────────────────────
[[ -f "$MODEL" ]]              || { echo "ERROR: LLM model not found: $MODEL"; exit 1; }
[[ -x "${LLAMA_SERVER:-}" ]]   || { echo "ERROR: llama-server not found under $BG_RUNTIME/llama.cpp"; exit 1; }

mkdir -p "$BG_LOGS" "$BG_RUN" \
  "$BG_WORKSPACE/database" "$BG_WORKSPACE/uploads" "$BG_WORKSPACE/cameras" \
  "$BG_WORKSPACE/indexes/construction_standards" "$BG_WORKSPACE/knowledge" \
  "$BG_WORKSPACE/events/images" "$BG_WORKSPACE/events/clips" \
  "$BG_WORKSPACE/logs/performance" "$BG_WORKSPACE/logs/audit" \
  "$BG_WORKSPACE/runtime" "$BG_WORKSPACE/reports" \
  "$BG_PVC/data" "$BG_PVC/reports/evaluation"

# ── Validate config ───────────────────────────────────────────────────────────
echo "--- Validating config ---"
buildguard validate-config --config "$CONFIG"

# ── Init workspace & DB ───────────────────────────────────────────────────────
echo "--- Initialising workspace and database ---"
buildguard init-workspace --config "$CONFIG"
buildguard db-init        --config "$CONFIG"
buildguard db-check       --config "$CONFIG"

# ── Start llama.cpp ───────────────────────────────────────────────────────────
echo "--- Starting llama-server ---"
LLAMA_DIR=$(dirname "$LLAMA_SERVER")
export LD_LIBRARY_PATH="$LLAMA_DIR:${LD_LIBRARY_PATH:-}"

HELP_TEXT=$("$LLAMA_SERVER" --help 2>&1 || true)
LLAMA_ARGS=(-m "$MODEL" --host 127.0.0.1 --port 8080 -ngl 99 -c 8192)
grep -q -- '--jinja' <<< "$HELP_TEXT" && LLAMA_ARGS+=(--jinja)
grep -q -- '-fa'     <<< "$HELP_TEXT" && LLAMA_ARGS+=(-fa on)

"$LLAMA_SERVER" "${LLAMA_ARGS[@]}" > "$BG_LOGS/llama.log" 2>&1 &
echo $! > "$BG_RUN/llama.pid"
echo "llama-server PID: $(cat $BG_RUN/llama.pid)"

echo "--- Waiting for LLM (up to 90s) ---"
for i in $(seq 1 45); do
  curl -sf http://127.0.0.1:8080/health > /dev/null 2>&1 && echo "LLM ready." && break
  [[ $i -eq 45 ]] && { echo "ERROR: LLM did not start. Check $BG_LOGS/llama.log"; exit 1; }
  sleep 2
done

# ── Start API ─────────────────────────────────────────────────────────────────
echo "--- Starting BuildGuard API on :8000 ---"
buildguard serve-api --config "$CONFIG" > "$BG_LOGS/api.log" 2>&1 &
echo $! > "$BG_RUN/api.pid"

sleep 4
curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1 \
  && echo "API ready." \
  || echo "WARNING: API not yet healthy — check $BG_LOGS/api.log"

# ── Start UI ──────────────────────────────────────────────────────────────────
echo "--- Starting BuildGuard UI on :8501 ---"
buildguard serve-ui --config "$CONFIG" > "$BG_LOGS/ui.log" 2>&1 &
echo $! > "$BG_RUN/ui.pid"

echo ""
echo "=== All services started ==="
echo "  API : http://127.0.0.1:8000"
echo "  UI  : http://127.0.0.1:8501"
echo "  LLM : http://127.0.0.1:8080"
echo "  Logs: $BG_LOGS/"
echo ""
echo "SSH tunnel from Windows:"
echo "  ssh -p <PORT> -L 8000:127.0.0.1:8000 -L 8501:127.0.0.1:8501 root@<HOST>"
