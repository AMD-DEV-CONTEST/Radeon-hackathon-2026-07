#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}Starting Bunker Entrypoint...${NC}"

# 1. Print ROCm info
echo "=== ROCm Info ==="
rocm-smi || true
rocminfo || true

# 2. Verify GPU detected or warn gracefully
if ! rocm-smi &> /dev/null; then
    echo -e "${YELLOW}WARNING: rocm-smi failed or no GPU detected. Proceeding with fallback mode...${NC}"
else
    echo -e "${GREEN}AMD GPU Detected successfully.${NC}"
fi

# 3. Start vLLM server in background
echo "Starting vLLM server..."
python3 -m vllm.entrypoints.openai.api_server \
    --model ${BUNKER__INFERENCE__PRIMARY_MODEL:-"Qwen/Qwen3-30B-A3B"} \
    --quantization ${BUNKER__INFERENCE__QUANTIZATION:-"gptq"} \
    --dtype ${BUNKER__INFERENCE__DTYPE:-"float16"} \
    --max-model-len ${BUNKER__INFERENCE__MAX_MODEL_LEN:-32768} \
    --port ${BUNKER__INFERENCE__VLLM_PORT:-8000} \
    --gpu-memory-utilization ${BUNKER__INFERENCE__GPU_MEMORY_UTILIZATION:-0.85} &
VLLM_PID=$!

# 7. Trap EXIT to clean up vLLM PID
trap "echo 'Stopping vLLM...'; kill $VLLM_PID || true" EXIT

# 4. Wait up to 120 seconds for vLLM health endpoint
echo "Waiting for vLLM to initialize..."
timeout=120
elapsed=0
vllm_ready=false
while [ $elapsed -lt $timeout ]; do
    if curl -s http://localhost:${BUNKER__INFERENCE__VLLM_PORT:-8000}/health > /dev/null; then
        vllm_ready=true
        break
    fi
    sleep 2
    elapsed=$((elapsed+2))
done

# 5. Handle vLLM start failure
if [ "$vllm_ready" = true ]; then
    echo -e "${GREEN}vLLM server is healthy and ready.${NC}"
else
    echo -e "${YELLOW}WARNING: vLLM failed to start after ${timeout}s. Radeon API fallback active.${NC}"
fi

# 6. Start Bunker app
echo "Starting Bunker application..."
python3 -m src.main
