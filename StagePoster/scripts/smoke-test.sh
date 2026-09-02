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
  else
    echo "Missing .env file. Looked in:" >&2
    echo "  $BACKEND_ROOT/.env" >&2
    echo "  $PROJECT_ROOT/.env" >&2
    echo "Copy .env.example to .env and edit it first." >&2
    exit 1
  fi
fi

set -a
source "$ENV_FILE"
set +a

failures=0

check_code() {
  local name="$1"
  local expected="$2"
  local url="$3"
  shift 3

  code="$(
    curl -sS \
      -o /tmp/stageposter-smoke-body \
      -w '%{http_code}' \
      "$@" \
      "$url" \
      || true
  )"

  if [[ "$code" == "$expected" ]]; then
    echo "$name OK HTTP=$code"
  else
    echo "$name FAILED HTTP=$code expected=$expected" >&2
    cat /tmp/stageposter-smoke-body >&2 || true
    failures=$((failures + 1))
  fi
}

check_code \
  "Backend router" \
  "404" \
  "http://127.0.0.1:8080/api/ai/sessions/not-found"

check_code \
  "ComfyUI" \
  "200" \
  "${COMFY_URL:-http://127.0.0.1:8188}/system_stats"

check_code \
  "vLLM models" \
  "200" \
  "${VLM_URL:-http://127.0.0.1:8001}/v1/models" \
  -H "Authorization: Bearer $VLM_API_KEY"

check_code \
  "vLLM sleep state" \
  "200" \
  "${VLM_URL:-http://127.0.0.1:8001}/is_sleeping" \
  -H "Authorization: Bearer $VLM_API_KEY"

if [[ -n "${PUBLIC_API_URL:-}" ]]; then
  check_code \
    "Public tunnel" \
    "404" \
    "${PUBLIC_API_URL}/api/ai/sessions/not-found"
fi

if [[ ! -f "$WORKFLOW_PATH" ]]; then
  echo "Workflow missing: $WORKFLOW_PATH" >&2
  failures=$((failures + 1))
else
  echo "Workflow OK: $WORKFLOW_PATH"
fi

for file in \
  "$COMFY_ROOT/models/diffusion_models/z_image_turbo_bf16.safetensors" \
  "$COMFY_ROOT/models/text_encoders/qwen_3_4b.safetensors" \
  "$COMFY_ROOT/models/vae/ae.safetensors"; do

  if [[ -f "$file" ]]; then
    echo "Model OK: $file"
  else
    echo "Model missing: $file" >&2
    failures=$((failures + 1))
  fi
done

if [[ -d "$VLM_MODEL_PATH" ]]; then
  echo "VLM model OK: $VLM_MODEL_PATH"
else
  echo "VLM model missing: $VLM_MODEL_PATH" >&2
  failures=$((failures + 1))
fi

if [[ "$failures" -ne 0 ]]; then
  echo "SMOKE TEST FAILED: $failures checks failed" >&2
  exit 1
fi

echo
echo "STAGEPOSTER SMOKE TEST OK"
