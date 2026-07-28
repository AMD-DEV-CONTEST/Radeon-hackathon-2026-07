#!/bin/bash
# =============================================================================
# OmniKernel-ROCm — Radeon Cloud Setup Script
# AMD AI DevMaster Hackathon 2026
#
# Usage: bash scripts/setup_radeon_cloud.sh
# Run this ONCE on a fresh Radeon Cloud instance.
# =============================================================================

set -euo pipefail

echo "=============================================="
echo "  OmniKernel-ROCm — Radeon Cloud Setup"
echo "=============================================="

# --- 0. Basic environment check ---
echo ""
echo "[1/8] Checking ROCm installation..."
if command -v rocm-smi &>/dev/null; then
    rocm-smi --showproductname
    echo "  ✓ rocm-smi found"
else
    echo "  ✗ rocm-smi not found. Is ROCm installed on this instance?"
    echo "  Refer to the contest repo README for environment setup."
    exit 1
fi

ROCM_VERSION=$(rocm-smi --version 2>/dev/null | head -1 || echo "unknown")
echo "  ROCm version: $ROCM_VERSION"

# --- 1. Python environment ---
echo ""
echo "[2/8] Setting up Python environment..."
PYTHON_VERSION=$(python3 --version 2>&1)
echo "  Python: $PYTHON_VERSION"

if ! command -v pip3 &>/dev/null; then
    echo "  Installing pip..."
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3
fi

# Create a virtual environment for isolation with system site packages (inherits container PyTorch/ROCm/vLLM)
if [ ! -d ".venv" ]; then
    python3 -m venv --system-site-packages .venv
    echo "  ✓ Created .venv (with system site-packages)"
fi
source .venv/bin/activate
echo "  ✓ Activated .venv"

# --- 2. Install PyTorch with ROCm backend ---
echo ""
echo "[3/8] Checking PyTorch with ROCm support..."
if python3 -c "import torch; print(torch.__version__)" 2>/dev/null; then
    echo "  ✓ PyTorch already installed ($(python3 -c 'import torch; print(torch.__version__)'))"
else
    echo "  Installing PyTorch ROCm build..."
    pip install torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/rocm6.0 || true
    echo "  ✓ PyTorch installed"
fi

# --- 3. Install project dependencies ---
echo ""
echo "[4/8] Installing project dependencies..."
pip install -r requirements.txt
echo "  ✓ Dependencies installed"

# --- 4. Install vLLM with ROCm backend ---
echo ""
echo "[5/8] Installing vLLM (ROCm backend)..."
if python3 -c "import vllm" 2>/dev/null; then
    echo "  ✓ vLLM already installed"
else
    pip install vllm
    echo "  ✓ vLLM installed"
fi

# --- 5. Download quantized model ---
echo ""
echo "[6/8] Downloading quantized model..."
MODEL_DIR="$HOME/models"
mkdir -p "$MODEL_DIR"

MODEL_NAME="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"
MODEL_LOCAL_PATH="$MODEL_DIR/qwen2.5-coder-7b-awq"

if [ -d "$MODEL_LOCAL_PATH" ]; then
    echo "  ✓ Model already downloaded at $MODEL_LOCAL_PATH"
else
    echo "  Downloading $MODEL_NAME..."
    echo "  (This may take several minutes depending on bandwidth)"
    pip install huggingface_hub
    python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='$MODEL_NAME',
    local_dir='$MODEL_LOCAL_PATH',
    ignore_patterns=['*.bin'],  # prefer .safetensors
)
print('  ✓ Model downloaded')
"
fi

# --- 6. Build RAG index ---
echo ""
echo "[7/8] Building RAG index from corpus/..."
if [ -z "$(ls -A corpus/ 2>/dev/null)" ]; then
    echo "  ⚠ corpus/ is empty. Skipping index build."
    echo "  Add .md/.txt files to corpus/ then run:"
    echo "    python3 -c \"from src.rag.index_builder import build_index; build_index()\""
else
    python3 -c "
from src.rag.index_builder import build_index
result = build_index()
if result['error']:
    print(f'  ✗ Index build failed: {result[\"error\"]}')
else:
    print(f'  ✓ Index built: {result[\"num_chunks\"]} chunks ({result[\"backend\"]} backend)')
"
fi

# --- 7. Start vLLM server (background) ---
echo ""
echo "[8/8] Starting vLLM server..."
if pgrep -f "vllm serve" > /dev/null; then
    echo "  ✓ vLLM server already running"
else
    echo "  Starting vLLM server in background..."
    nohup vllm serve "$MODEL_LOCAL_PATH" \
        --port 8000 \
        --gpu-memory-utilization 0.85 \
        --max-model-len 4096 \
        > vllm_server.log 2>&1 &
    VLLM_PID=$!
    echo "  vLLM PID: $VLLM_PID"
    echo "  Waiting 30s for server to start..."
    sleep 30

    # Health check
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "  ✓ vLLM server is up"
    else
        echo "  ⚠ vLLM server may still be starting. Check vllm_server.log"
    fi
fi

# --- Done ---
echo ""
echo "=============================================="
echo "  Setup complete!"
echo "=============================================="
echo ""
echo "  To run the agent:"
echo "    source .venv/bin/activate"
echo "    python3 -m src.main --codebase ./cases --llm-url http://localhost:8000/v1"
echo ""
echo "  To run tests:"
echo "    python3 -m pytest tests/ -v"
echo ""
echo "  To check vLLM server logs:"
echo "    tail -f vllm_server.log"
echo ""
