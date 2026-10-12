#!/bin/bash
# Warden — AMD Radeon Cloud GPU setup script
# Run this on the AMD Radeon Cloud instance to set up the environment.

set -e

echo "=== Warden Cloud GPU Setup ==="
echo "Date: $(date -u)"
echo "Host: $(hostname)"

# 1. Check ROCm
echo -e "\n--- ROCm Version ---"
rocm-smi --version || echo "WARNING: rocm-smi not found"
rocminfo | head -20 || echo "WARNING: rocminfo not found"

# 2. Check GPU
echo -e "\n--- GPU Detection ---"
rocm-smi --showproductname || echo "WARNING: No GPU detected"
rocm-smi --showmeminfo vram || echo "WARNING: Cannot read VRAM"

# 3. Python environment
echo -e "\n--- Python Setup ---"
python3 --version
python3 -m venv .venv 2>/dev/null || echo "venv already exists"
source .venv/bin/activate

# 4. Install dependencies
echo -e "\n--- Installing Dependencies ---"
pip install -r requirements.txt

# 5. Build llama-cpp-python with ROCm
echo -e "\n--- Building llama-cpp-python with ROCm ---"
CMAKE_ARGS="-DGGML_HIP=on -DGGML_HIPBLAS=on" pip install llama-cpp-python --force-reinstall --no-cache-dir

# 6. Verify GPU inference
echo -e "\n--- Verifying GPU Inference ---"
python3 -c "
from llama_cpp import Llama
print('llama-cpp-python imported successfully')
print('ROCm backend should be active')
"

echo -e "\n=== Setup Complete ==="
echo "Next: download a GGUF model and run: python -m warden check 'test input'"
