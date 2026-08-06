#!/usr/bin/env bash
#
# setup.sh — Project R.A.G.E. (ROCm-Accelerated Generalist Embodiment)
# Environment setup for AMD ROCm GPU platform.
#
set -euo pipefail

echo "=================================================="
echo " R.A.G.E. - Environment Setup"
echo "=================================================="

# 1. Ensure Python 3.12 is available
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 could not be found. Please install Python 3." >&2
    exit 1
fi

# 2. Virtual Environment Setup
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Creating Python virtual environment at './$VENV_DIR'..."
    python3 -m venv "$VENV_DIR"
else
    echo "==> Virtual environment '$VENV_DIR' already exists."
fi

# Activate environment for script context
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# 3. Upgrade Core Build Tools
echo "==> Upgrading pip, setuptools, wheel..."
pip install --upgrade pip setuptools wheel --quiet

# 4. Install Native PyTorch with ROCm 7.2 Support
echo "==> Installing PyTorch + ROCm 7.2 stack..."
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/rocm7.2

# 5. Install Project Dependencies (Including torch explicitly to prevent re-downloading)
echo "==> Installing Genesis, OpenVLA, VLM, and auxiliary tools..."
pip install \
    torch torchvision torchaudio \
    genesis-world \
    "transformers>=4.57.0" \
    accelerate \
    ultralytics \
    huggingface_hub \
    qwen-vl-utils \
    pymilvus \
    lerobot \
    timm \
    einops \
    opencv-python-headless \
    pillow \
    numpy \
    pandas \
    matplotlib \
    seaborn \
    psutil \
    py-cpuinfo \
    requests \
    tqdm \
    --extra-index-url https://download.pytorch.org/whl/rocm7.2

# 6. Verification
echo ""
echo "=================================================="
echo " Verification "
echo "=================================================="
python3 -c "
import torch, genesis, transformers, ultralytics
print(f' PyTorch Version   : {torch.__version__}')
print(f' ROCm GPU Visible : {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f' Device Name       : {torch.cuda.get_device_name(0)}')
print(f' Genesis Engine    : {genesis.__version__}')
print(f' HuggingFace       : {transformers.__version__}')
print(f' Ultralytics (YOLO): {ultralytics.__version__}')
"

echo "=================================================="
echo " Setup complete! To activate run: source venv/bin/activate"
echo "=================================================="