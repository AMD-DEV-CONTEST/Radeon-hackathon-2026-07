#!/bin/bash
# Build the PrismML llama.cpp fork and download the Ternary-Bonsai-27B GGUF.
# This is a one-time setup script.
set -e

# Configuration
LLAMA_PRISMML_DIR="${LLAMA_PRISMML_DIR:-/tmp/llama-prismml}"
MODEL_DIR="${MODEL_DIR:-$(dirname "$0")/../backend/models/chat}"
CUDA_ARCHS="${CUDA_ARCHS:-80}"

echo "=== Setting up Ternary-Bonsai-27B chat server ==="
echo "Build dir: $LLAMA_PRISMML_DIR"
echo "Model dir: $MODEL_DIR"
echo "CUDA arch: $CUDA_ARCHS"

# 1. Clone the PrismML fork
if [ ! -d "$LLAMA_PRISMML_DIR" ]; then
    echo "[1/4] Cloning PrismML llama.cpp fork..."
    git clone --depth 1 https://github.com/PrismML-Eng/llama.cpp.git "$LLAMA_PRISMML_DIR"
else
    echo "[1/4] PrismML fork already exists at $LLAMA_PRISMML_DIR"
fi

cd "$LLAMA_PRISMML_DIR"

# 2. Build with CUDA
echo "[2/4] Building llama-server with CUDA (arch=$CUDA_ARCHS)..."
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCHS"
cmake --build build -j --target llama-server

echo "[3/4] Verifying build..."
"$LLAMA_PRISMML_DIR/build/bin/llama-server" --version

# 3. Download the ternary GGUF
echo "[4/4] Downloading Ternary-Bonsai-27B-Q2_0.gguf..."
mkdir -p "$MODEL_DIR"
python - <<'PY' - "$MODEL_DIR"
import os
import sys
from huggingface_hub import hf_hub_download

local_dir = sys.argv[1]
os.makedirs(local_dir, exist_ok=True)
hf_hub_download(
    repo_id="prism-ml/Ternary-Bonsai-27B-gguf",
    filename="Ternary-Bonsai-27B-Q2_0.gguf",
    local_dir=local_dir,
)
print(f"Downloaded to {local_dir}/Ternary-Bonsai-27B-Q2_0.gguf")
PY

echo ""
echo "=== Setup complete ==="
echo "Server binary: $LLAMA_PRISMML_DIR/build/bin/llama-server"
echo "Model file:    $MODEL_DIR/Ternary-Bonsai-27B-Q2_0.gguf"
echo ""
echo "Start the server with:"
echo "  scripts/start_ternary_server.sh"
echo "Then start the backend with:"
echo "  scripts/start_backend_with_ternary.sh"
