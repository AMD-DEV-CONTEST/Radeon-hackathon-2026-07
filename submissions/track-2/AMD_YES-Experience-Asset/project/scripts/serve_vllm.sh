#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
VENV="${VLLM_VENV:-$ROOT/venvs/vllm}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$(dirname "$SCRIPT_DIR")}"
MODEL_PATH="${MODEL_PATH:-${MODEL_ID:-$ROOT/models/Qwen2.5-14B-Instruct-3957bf39753c}}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-Qwen2.5-14B-Instruct}"
MODEL_MANIFEST="${MODEL_MANIFEST:-$REPO/config/models/qwen2.5-14b-instruct.modelscope.json}"
MODEL_SNAPSHOT_VERIFY="${MODEL_SNAPSHOT_VERIFY:-1}"
HOST="${VLLM_HOST:-${HOST:-127.0.0.1}}"
PORT="${VLLM_PORT:-${PORT:-8000}}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.82}"
MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-4}"
TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-hermes}"

export HF_HOME="${HF_HOME:-$ROOT/cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

if [[ ! -x "$VENV/bin/vllm" ]]; then
  echo "ERROR: vLLM executable not found at $VENV/bin/vllm"
  echo "Run scripts/install_vllm_rocm721.sh first."
  exit 1
fi

if [[ "$MODEL_SNAPSHOT_VERIFY" == "1" ]]; then
  "$VENV/bin/python" "$REPO/scripts/verify_model_snapshot.py" \
    --manifest "$MODEL_MANIFEST" \
    --model-dir "$MODEL_PATH"
elif [[ "$MODEL_SNAPSHOT_VERIFY" != "0" ]]; then
  echo "ERROR: MODEL_SNAPSHOT_VERIFY must be 0 or 1."
  exit 1
else
  echo "WARN: model snapshot verification is disabled; this run is not submission evidence."
fi

echo "Serving $MODEL_PATH as $SERVED_MODEL_NAME on $HOST:$PORT"
echo "This enables structured model tool-call output; application permissions remain the Agent runtime's responsibility."
if [[ "$HOST" != "127.0.0.1" && "$HOST" != "localhost" ]]; then
  echo "ERROR: the private vLLM wrapper only permits a localhost bind."
  echo "Expose an authenticated application/Web UI, never this raw inference API."
  exit 1
fi

# These VLLM_* names belong to this wrapper, not to vLLM itself. Remove them
# before exec so vLLM does not report them as unknown environment variables.
unset VLLM_HOST VLLM_PORT VLLM_MAX_MODEL_LEN
unset VLLM_GPU_MEMORY_UTILIZATION VLLM_MAX_NUM_SEQS VLLM_TOOL_CALL_PARSER

exec "$VENV/bin/vllm" serve "$MODEL_PATH" \
  --served-model-name "$SERVED_MODEL_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --dtype bfloat16 \
  --generation-config vllm \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --enable-auto-tool-choice \
  --tool-call-parser "$TOOL_CALL_PARSER"
