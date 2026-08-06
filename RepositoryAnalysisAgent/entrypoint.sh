#!/usr/bin/env bash
set -e

echo "=========================================="
echo "  RepositoryAnalysisAgent Docker Container"
echo "=========================================="

# Belt and suspenders: ensure flash-attn is gone
pip uninstall -y flash-attn flash-attn-rotary 2>/dev/null || true

# ── Model path ──
MODEL_PATH="${MODEL_PATH:-${MODEL_DIR}/Qwen2.5-Coder-14B-Instruct}"
echo "[entrypoint] Model: $MODEL_PATH"
echo "[entrypoint] Repo:  $REPO_PATH"

# ── Mode selection ──
case "${1:-all}" in

  # Start both vLLM + RepositoryAnalysisAgent
  all)
    echo ""
    echo "[entrypoint] Starting vLLM in background..."
    echo ""

    # Start vLLM
    vllm serve "$MODEL_PATH" \
      --dtype float16 \
      --max-model-len 32768 \
      --gpu-memory-utilization 0.88 \
      --enable-auto-tool-choice \
      --tool-call-parser hermes \
      --enforce-eager \
      --port 8000 &

    VLLM_PID=$!

    # Wait for vLLM to be ready
    echo "[entrypoint] Waiting for vLLM to be ready..."
    for i in $(seq 1 120); do
      if curl -sf http://127.0.0.1:8000/v1/models >/dev/null 2>&1; then
        echo "[entrypoint] vLLM is ready!"
        break
      fi
      sleep 5
      echo "  ... waiting ($((i*5))s)"
    done

    if ! curl -sf http://127.0.0.1:8000/v1/models >/dev/null 2>&1; then
      echo "[entrypoint] ERROR: vLLM failed to start within 10 minutes"
      exit 1
    fi

    echo ""
    echo "[entrypoint] Starting RepositoryAnalysisAgent..."
    echo ""

    # Start RepositoryAnalysisAgent in foreground
    cd /app
    exec python -m src.server "${REPO_PATH}" --host 0.0.0.0
    ;;

  # Only vLLM
  vllm)
    exec vllm serve "$MODEL_PATH" \
      --dtype float16 \
      --max-model-len 32768 \
      --gpu-memory-utilization 0.88 \
      --enable-auto-tool-choice \
      --tool-call-parser hermes \
      --enforce-eager \
      --port 8000
    ;;

  # Only RepositoryAnalysisAgent (vLLM must be running separately)
  app)
    cd /app
    exec python -m src.server "${REPO_PATH}" --host 0.0.0.0
    ;;

  # Shell
  shell)
    exec /bin/bash
    ;;

  *)
    echo "Usage: docker run ... [all|vllm|app|shell]"
    echo "  all   (default) Start vLLM + RepositoryAnalysisAgent together"
    echo "  vllm  Start only vLLM"
    echo "  app   Start only RepositoryAnalysisAgent"
    echo "  shell Drop into bash"
    exit 1
    ;;
esac
