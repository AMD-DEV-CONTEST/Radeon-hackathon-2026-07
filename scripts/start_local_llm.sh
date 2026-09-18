#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"
source "$SCRIPT_DIR/process_helpers.sh"

MODEL="${BG_LLM_MODEL:-$BG_MODELS/llm/qwen3-14b-q8/Qwen3-14B-Q8_0.gguf}"

LLAMA_SERVER=$(
  find "${BG_LLAMA_DIR:-$BG_RUNTIME/llama.cpp}" \
    -type f \
    -name llama-server \
    -print \
    -quit
)

if [[ -z "${LLAMA_SERVER:-}" || ! -x "$LLAMA_SERVER" ]]; then
  echo "ERROR: llama-server 不存在或不可执行"
  exit 1
fi

if [[ ! -f "$MODEL" ]]; then
  echo "ERROR: 模型文件不存在：$MODEL"
  exit 1
fi

"$BG_VENV/bin/python" "$SCRIPT_DIR/verify_model_manifest.py" \
  "$MODEL" "$(dirname "$MODEL")/model-manifest.json"
"$BG_VENV/bin/python" "$SCRIPT_DIR/verify_rocm_runtime.py"

LLAMA_DIR=$(dirname "$LLAMA_SERVER")
export LD_LIBRARY_PATH="$LLAMA_DIR:${LD_LIBRARY_PATH:-}"

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export NO_PROXY=127.0.0.1,localhost,::1

HELP_TEXT=$("$LLAMA_SERVER" --help 2>&1 || true)

ARGS=(
  -m "$MODEL"
  --host 127.0.0.1
  --port 8080
  -ngl 99
  -c "${BG_LLM_CONTEXT:-8192}"
)

if grep -q -- '--jinja' <<<"$HELP_TEXT"; then
  ARGS+=(--jinja)
fi

if grep -q -- '-fa' <<<"$HELP_TEXT"; then
  ARGS+=(-fa on)
fi

if [[ "${BG_PREFIX_CACHE_ENABLED:-1}" == "1" ]] && \
  grep -q -- '--cache-reuse' <<<"$HELP_TEXT"; then
  ARGS+=(--cache-reuse "${BG_PREFIX_CACHE_REUSE:-256}")
  echo "PREFIX_CACHE=explicit cache-reuse ${BG_PREFIX_CACHE_REUSE:-256}"
elif [[ "${BG_PREFIX_CACHE_ENABLED:-1}" == "1" ]]; then
  echo "PREFIX_CACHE=server-native KV cache (cache-reuse option unavailable)"
else
  echo "PREFIX_CACHE_REUSE=disabled; set llm.cache_prompt=false in the off variant"
fi

bg_require_free_port 8080
echo "LLAMA_SERVER=$LLAMA_SERVER"
echo "MODEL=$MODEL"
echo "CONTEXT=${BG_LLM_CONTEXT:-8192}"
echo "ARGS=${ARGS[*]}"

nohup env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" "$LLAMA_SERVER" "${ARGS[@]}" \
  >"$BG_LOGS/llama-server.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$BG_RUN/llama-server.pid"
echo "llama-server PID=$pid; log=$BG_LOGS/llama-server.log"
