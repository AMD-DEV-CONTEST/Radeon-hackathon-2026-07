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

show_process() {
  local name="$1"
  local file="$2"

  if [[ ! -f "$file" ]]; then
    echo "$name: STOPPED"
    return
  fi

  local pid
  pid="$(cat "$file")"

  if kill -0 "$pid" 2>/dev/null; then
    echo "$name: RUNNING PID=$pid"
  else
    echo "$name: STALE PID FILE"
  fi
}

show_process "vLLM" "$BACKEND_ROOT/run/vllm.pid"
show_process "ComfyUI" "$BACKEND_ROOT/run/comfyui.pid"
show_process "Backend" "$BACKEND_ROOT/run/backend.pid"
show_process "Cloudflare" "$BACKEND_ROOT/run/cloudflared.pid"

echo
echo "HTTP checks:"

VLM_STATE="$(
  curl -sS \
    -H "Authorization: Bearer ${VLM_API_KEY:-}" \
    "${VLM_URL:-http://127.0.0.1:8001}/is_sleeping" \
    2>/dev/null \
    || true
)"

echo "VLM: ${VLM_STATE:-unreachable}"

COMFY_CODE="$(
  curl -sS \
    -o /dev/null \
    -w '%{http_code}' \
    "${COMFY_URL:-http://127.0.0.1:8188}/system_stats" \
    2>/dev/null \
    || true
)"

echo "ComfyUI HTTP: ${COMFY_CODE:-unreachable}"

BACKEND_CODE="$(
  curl -sS \
    -o /dev/null \
    -w '%{http_code}' \
    "http://127.0.0.1:8080/api/ai/sessions/not-found" \
    2>/dev/null \
    || true
)"

echo "Backend HTTP: ${BACKEND_CODE:-unreachable}"

if [[ -f "$BACKEND_ROOT/logs/cloudflared.log" ]]; then
  PUBLIC_URL="$(
    grep -oE \
      'https://[a-zA-Z0-9-]+\.trycloudflare\.com' \
      "$BACKEND_ROOT/logs/cloudflared.log" \
    | tail -1 \
    || true
  )"

  echo "Public URL: ${PUBLIC_URL:-not found}"
fi

echo
if command -v rocm-smi >/dev/null 2>&1; then
  rocm-smi --showmeminfo vram || true
fi
