#!/bin/bash
# aiQuant ROCm Environment Setup Script
set -e

echo "=== aiQuant ROCm Environment Setup ==="

# 1. Verify ROCm
echo "[1/5] Verifying ROCm environment..."
rocminfo | grep "Device ID" || { echo "ERROR: ROCm not found"; exit 1; }
echo "ROCm detected."

# 2. Install Python dependencies
echo "[2/5] Installing Python dependencies..."
pip install -r src/requirements.txt

# 3. Install vLLM for local inference
echo "[3/5] Installing vLLM..."
pip install vllm

# 4. Start local LLM service
echo "[4/5] Starting vLLM local inference service..."
vllm serve Qwen/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 --port 8000 --dtype float16 &
VLLM_PID=$!
echo "vLLM PID: $VLLM_PID"

# 5. Wait for vLLM to be ready
echo "[5/5] Waiting for vLLM service..."
for i in $(seq 1 60); do
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "vLLM is ready!"
    break
  fi
  sleep 5
done

echo ""
echo "=== Environment setup complete! ==="
echo "Start aiQuant:  bash scripts/start.sh"
echo "Web UI:         http://localhost:8008"
