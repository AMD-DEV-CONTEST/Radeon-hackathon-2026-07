#!/bin/bash
# aiQuant Demo Script
cd "$(dirname "$0")/.."

echo "=== aiQuant Demo ==="

# Check environment
echo "[1] Checking ROCm..."
rocm-smi | grep GPU || { echo "No AMD GPU found"; exit 1; }

echo "[2] Checking LLM service..."
curl -s http://localhost:8000/health && echo " OK" || { echo "LLM service not ready"; exit 1; }

echo "[3] Starting aiQuant..."
bash scripts/start.sh &

sleep 10

echo "[4] Sending demo command..."
curl -X POST http://localhost:8008/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Mine momentum factors for CSI 500, 1 iteration"}'

echo ""
echo "=== Demo running at http://localhost:8008 ==="
