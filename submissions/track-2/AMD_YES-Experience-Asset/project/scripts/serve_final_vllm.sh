#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
VENV="${VLLM_VENV:-$ROOT/venvs/vllm-026-qwen35}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$(dirname "$SCRIPT_DIR")}"
MODEL_PATH="${MODEL_PATH:-$ROOT/models/Qwen3.5-9B-460979c3d118}"
MODEL_MANIFEST="${MODEL_MANIFEST:-$REPO/config/models/qwen3.5-9b.modelscope.json}"
PROFILE="${SERVING_PROFILE:-P1-prefix-cache}"
HOST="${VLLM_HOST:-127.0.0.1}"
PORT="${VLLM_PORT:-8000}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-20000}"
GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.82}"
MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-2}"

export HF_HOME="${HF_HOME:-$ROOT/cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

if [[ "$HOST" != "127.0.0.1" && "$HOST" != "localhost" ]]; then
  echo "ERROR: the private vLLM wrapper only permits a localhost bind."
  exit 1
fi
if [[ ! -x "$VENV/bin/vllm" ]]; then
  echo "ERROR: frozen vLLM executable not found at $VENV/bin/vllm"
  exit 1
fi

case "$PROFILE" in
  P1-prefix-cache)
    PROFILE_ARGS=(--enable-prefix-caching)
    ;;
  S0)
    PROFILE_ARGS=()
    ;;
  *)
    echo "ERROR: SERVING_PROFILE must be P1-prefix-cache or S0."
    exit 1
    ;;
esac

"$VENV/bin/python" "$REPO/scripts/verify_model_snapshot.py" \
  --manifest "$MODEL_MANIFEST" \
  --model-dir "$MODEL_PATH"

echo "Serving final profile $PROFILE on $HOST:$PORT"
echo "Model tool calls remain proposals; the Agent Runtime owns execution permission."

unset VLLM_HOST VLLM_PORT VLLM_MAX_MODEL_LEN
unset VLLM_GPU_MEMORY_UTILIZATION VLLM_MAX_NUM_SEQS

exec "$VENV/bin/vllm" serve "$MODEL_PATH" \
  --served-model-name Qwen3.5-9B \
  --host "$HOST" \
  --port "$PORT" \
  --dtype bfloat16 \
  --generation-config vllm \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --language-model-only \
  "${PROFILE_ARGS[@]}"
