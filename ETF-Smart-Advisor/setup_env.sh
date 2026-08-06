#!/bin/bash
# setup_env.sh - One-click setup script for AMD ROCm 7.2.1 environment

set -e

echo "=============================================="
echo "🚀 ETF-Smart Advisor Environment Setup"
echo "=============================================="

# 1. Get project root directory
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "📁 Project directory: $PROJECT_DIR"

# 2. Check ROCm environment
echo ""
echo "🔍 Checking ROCm environment..."
if command -v rocm-smi &> /dev/null; then
    echo "✅ ROCm detected successfully!"
    rocm-smi --showproductname
else
    echo "❌ ROCm not detected, please install ROCm first"
    exit 1
fi

# 3. Create virtual environment
echo ""
echo "📦 Creating Python virtual environment (etfadvisorvenv)..."
if [ -d "etfadvisorvenv" ]; then
    echo "⚠️ Virtual environment already exists, removing old one..."
    rm -rf etfadvisorvenv
fi
python3 -m venv etfadvisorvenv
source etfadvisorvenv/bin/activate

apt-get update
apt-get install unzip zip -y
# 4. Upgrade pip
echo ""
echo "⬆️ Upgrading pip..."
pip install --upgrade pip

# 5. Install milvus-lite
echo ""
echo "Installing milvus-lite..."
pip install pymilvus sentence-transformers milvus-lite
export MILVUS_MODE=lite

# 6. Install PyTorch dependencies
echo ""
echo "Installing PyTorch dependencies..."
pip install typing_extensions numpy

# 7. Download and install ROCm PyTorch
echo ""
echo "📥 Installing ROCm PyTorch (2.9.1+rocm7.2.1)..."
cd /tmp

# Define wheel filenames
PYTORCH_WHEEL="torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl"
TORCHVISION_WHEEL="torchvision-0.24.0+rocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl"
TORCHAUDIO_WHEEL="torchaudio-2.9.0+rocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl"
TRITON_WHEEL="triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl"

# Download function
download_if_missing() {
    local url="https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/$1"
    local file="$1"
    if [ ! -f "$file" ]; then
        echo "  Downloading $file..."
        wget -q --show-progress "$url" -O "$file" || echo "  ⚠️ Download failed, continuing..."
    else
        echo "  ✅ $file already exists"
    fi
}

echo "  Checking and downloading wheel files..."
download_if_missing "$PYTORCH_WHEEL"
download_if_missing "$TORCHVISION_WHEEL"
download_if_missing "$TORCHAUDIO_WHEEL"
download_if_missing "$TRITON_WHEEL"

echo "  Installing PyTorch components..."
pip install "$PYTORCH_WHEEL" "$TORCHVISION_WHEEL" "$TORCHAUDIO_WHEEL" "$TRITON_WHEEL"
# pip install causal-conv1d --find-links https://download.pytorch.org/whl/rocm5.6/torch_stable.html

# 8. Verify PyTorch
echo ""
echo "🔬 Verifying PyTorch installation..."
python -c "
import torch
print(f'✅ PyTorch version: {torch.__version__}')
print(f'✅ GPU available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'✅ GPU name: {torch.cuda.get_device_name(0)}')
    print(f'✅ Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB')
"

# 9. Install uv and vLLM
echo ""
echo "📦 Installing uv and vLLM (ROCm version)..."
pip install uv
uv pip install vllm --upgrade \
    --extra-index-url https://wheels.vllm.ai/rocm/

# 10. Install other project dependencies
echo ""
echo "📦 Installing other project dependencies..."
cd "$PROJECT_DIR"
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 11. Create data directories
echo ""
echo "📁 Creating data directories..."
# mkdir -p  knowledge

# 12. Download Qwen model
echo ""
echo "📥 Downloading Qwen model..."
pip install huggingface_hub

python -c "
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path('.').resolve()))

try:
    from app.config import LLM_MODEL_ID, LLM_MODEL_PATH
except ImportError:
    print('❌ Cannot import config.py')
    sys.exit(1)

from huggingface_hub import snapshot_download

print(f'📥 Downloading: {LLM_MODEL_ID}')
print(f'📁 Target path: {LLM_MODEL_PATH}')

snapshot_download(
    repo_id=LLM_MODEL_ID,
    local_dir=LLM_MODEL_PATH,
    local_dir_use_symlinks=False,
    resume_download=True,
    ignore_patterns=['*.h5', '*.ot', '*.msgpack']
)
print(f'✅ Model downloaded to: {LLM_MODEL_PATH}')
"

# 13. Clean up temporary files
cleanup_temp_files() {
    echo ""
    echo "🧹 Cleaning up temporary files to save disk space..."
    local tmp_files=(
        "/tmp/$PYTORCH_WHEEL"
        "/tmp/$TORCHVISION_WHEEL"
        "/tmp/$TORCHAUDIO_WHEEL"
        "/tmp/$TRITON_WHEEL"
    )
    local freed_space=0
    for file in "${tmp_files[@]}"; do
        if [ -f "$file" ]; then
            local size=$(du -b "$file" | cut -f1)
            freed_space=$((freed_space + size))
            rm -f "$file"
            echo "  Deleted: $(basename "$file") ($(numfmt --to=iec $size))"
        fi
    done
    pip cache purge 2>/dev/null || true
    uv cache clean 2>/dev/null || true
    if [ $freed_space -gt 0 ]; then
        echo "  ✅ Freed space: $(numfmt --to=iec $freed_space)"
    else
        echo "  ✅ No files to clean"
    fi
}

echo ""
echo "💡 Clean up temporary wheel files? (approx 2GB)"
read -p "  Enter y to confirm, n to skip (default y): " -r CLEANUP_CHOICE
CLEANUP_CHOICE=${CLEANUP_CHOICE:-y}
if [[ "$CLEANUP_CHOICE" =~ ^[Yy]$ ]]; then
    cleanup_temp_files
else
    echo "  Skipping cleanup"
fi

# 14. Start the service
# echo ""
# echo "=============================================="
# echo "✅ Environment setup complete, starting service..."
# echo "=============================================="
# echo ""

# source etfadvisorvenv/bin/activate
# bash scripts/start.sh