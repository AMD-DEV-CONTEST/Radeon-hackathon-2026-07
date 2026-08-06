#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"
"$BG_VENV/bin/python" "$SCRIPT_DIR/verify_rocm_runtime.py"
"$BG_VENV/bin/python" "$SCRIPT_DIR/verify_model_inventory.py" \
  "$BG_REPO/configs/competition/models.yaml"
"$SCRIPT_DIR/start_local_llm.sh"
echo "Launching LLM server..."
llm_ready=false
for i in $(seq 1 180); do
  if curl -fsSo /dev/null --max-time 2 http://127.0.0.1:8080/v1/models 2>/dev/null; then
    llm_ready=true
    break
  fi
  printf '\r  launching... (%ds elapsed)' "$((i * 2))"
  sleep 2
done
printf '\r'
[[ "$llm_ready" == true ]] || {
  echo "LLM server did not become healthy after 6 min" >&2
  exit 1
}
"$SCRIPT_DIR/start_api.sh"
echo "Launching BuildGuard API..."
api_ready=false
for i in $(seq 1 120); do
  if curl -fsSo /dev/null --max-time 2 http://127.0.0.1:8000/health 2>/dev/null; then
    api_ready=true
    break
  fi
  printf '\r  launching... (%ds elapsed)' "$((i * 2))"
  sleep 2
done
printf '\r'
[[ "$api_ready" == true ]] || {
  echo "BuildGuard API did not become healthy after 4 min" >&2
  exit 1
}
sleep 20
"$SCRIPT_DIR/start_ui.sh"
echo "Launching BuildGuard UI..."
ui_ready=false
for i in $(seq 1 90); do
  if curl -fsSo /dev/null --max-time 2 http://127.0.0.1:8501/_stcore/health 2>/dev/null; then
    ui_ready=true
    break
  fi
  printf '\r  launching... (%ds elapsed)' "$((i * 2))"
  sleep 2
done
printf '\r'
[[ "$ui_ready" == true ]] || {
  echo "BuildGuard UI did not become healthy after 3 min" >&2
  exit 1
}
"$SCRIPT_DIR/health_check.sh"
