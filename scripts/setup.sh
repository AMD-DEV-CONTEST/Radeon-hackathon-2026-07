#!/bin/bash
# One-command setup for Track 2 — Domestic-market Quant Agent on AMD ROCm
#
# Installs dependencies, prepares domestic-market data, and starts services.
# Run on the AMD GPU instance (安睿云).
#
# Usage:
#   bash scripts/setup.sh

set -euo pipefail

PYTHON="${VENV_PYTHON:-/opt/venv/bin/python}"
PIP="${VENV_PIP:-/opt/venv/bin/pip}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_PATH="${MODEL_PATH:-${PROJECT_ROOT}/models/qwen-trader-merged}"

echo "============================================"
echo "  Track 2: Domestic-market Quant Agent Setup"
echo "  AMD ROCm GPU Environment"
echo "============================================"
echo ""

# --- Check ROCm ---
echo "[1/6] Checking ROCm environment..."
if ! command -v rocm-smi &>/dev/null; then
    echo "WARNING: rocm-smi not found. ROCm may not be installed."
else
    rocm-smi --showproductname 2>/dev/null | head -5
fi

# --- Check GPU ---
echo ""
echo "[2/6] Checking PyTorch + ROCm..."
${PYTHON} -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'HIP available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'ROCm version: {torch.version.hip}')
" || { echo "ERROR: PyTorch not available"; exit 1; }

# --- Install Python dependencies ---
echo ""
echo "[3/6] Installing Python dependencies..."
${PIP} install --quiet \
    fastapi uvicorn pydantic httpx \
    ccxt pandas numpy pyyaml jsonschema \
    peft trl bitsandbytes datasets accelerate \
    openai pytest pytest-asyncio 2>&1 | tail -3

# Install TA-Lib (may need system library)
if ! ${PYTHON} -c "import talib" 2>/dev/null; then
    echo "[3/6] Installing TA-Lib..."
    ${PIP} install --quiet TA-Lib 2>&1 | tail -3 || \
        echo "WARNING: TA-Lib install failed. Install system lib: apt install ta-lib"
fi

# Install vLLM (ROCm)
if ! ${PYTHON} -c "import vllm" 2>/dev/null; then
    echo "[3/6] Installing vLLM (ROCm)..."
    ${PIP} install --quiet vllm 2>&1 | tail -5 || \
        echo "WARNING: vLLM install failed. Will use transformers fallback."
fi

# --- Prepare training data ---
echo ""
echo "[4/6] Preparing training data..."
cd "${PROJECT_ROOT}"

${PYTHON} training/data/generate_cn_market_pairs.py \
    --output training/data/processed/cn_market_train.jsonl \
    --count 400 --seed 20260730

# --- Check/download model ---
echo ""
echo "[5/6] Checking merged domestic-market model..."
if [ ! -f "${MODEL_PATH}/config.json" ]; then
    echo "ERROR: merged model not found at ${MODEL_PATH}"
    echo "Copy qwen-trader-cn-merged to this path or set MODEL_PATH."
    exit 1
else
    echo "Model found at ${MODEL_PATH}"
fi

# --- Start services ---
echo ""
echo "[6/6] Starting services..."

# Start Trading API server (background)
echo "  Starting Trading API on :8080..."
${PYTHON} -m uvicorn src.api:app --host 0.0.0.0 --port 8080 &
API_PID=$!
echo "  API PID: ${API_PID}"

# Wait for API to start
sleep 3
curl -s http://localhost:8080/health | head -1 || echo "  WARNING: API not ready yet"

# Start vLLM (background, if installed)
if ${PYTHON} -c "import vllm" 2>/dev/null; then
    echo "  Starting vLLM on :8000..."
    bash training/scripts/serve_vllm.sh "${MODEL_PATH}" &
    VLLM_PID=$!
    echo "  vLLM PID: ${VLLM_PID}"
else
    echo "  vLLM not installed. Skipping LLM server."
    echo "  Install with: ${PIP} install vllm"
fi

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Services:"
echo "  - Trading API:  http://localhost:8080/docs"
echo "  - vLLM (LLM):   http://localhost:8000/v1"
echo ""
echo "Next steps:"
echo "  1. Run QLoRA fine-tuning:"
echo "     ${PYTHON} training/scripts/train_qlora.py --data training/data/processed/merged_train.jsonl"
echo "  2. Merge LoRA weights:"
echo "     ${PYTHON} training/scripts/merge_lora.py --adapter-path models/qwen-trader-lora/final --output-path models/qwen-trader-merged"
echo "  3. Deploy Dify:"
echo "     cd docker && docker compose up -d"
echo "  4. Run submission verification:"
echo "     bash scripts/verify_submission.sh"
echo ""
echo "To stop services: kill ${API_PID} ${VLLM_PID:-}"
