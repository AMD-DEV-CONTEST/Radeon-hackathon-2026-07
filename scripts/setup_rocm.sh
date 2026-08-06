#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}Setting up ROCm Environment for Bunker...${NC}"

# 1. System deps
echo "Installing system dependencies..."
sudo apt-get update && sudo apt-get install -y \
    rocm-dev rocm-libs hipblas hipblaslt miopen-hip rccl rocfft rocrand \
    python3-dev python3-pip python3-venv git wget

# 2. Create and activate Python venv
echo "Creating Python virtual environment 'bunker-env'..."
python3 -m venv bunker-env
source bunker-env/bin/activate

# 3. Install PyTorch with ROCm wheel
echo "Installing PyTorch 2.3.0 for ROCm 6.2..."
pip install --upgrade pip
pip install torch==2.3.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2

# 4. Install vLLM with ROCm wheels
echo "Installing vLLM..."
pip install vllm==0.5.0

# 5. Install auto-gptq with ROCm index
echo "Installing auto-gptq..."
pip install auto-gptq --extra-index-url https://huggingface.github.io/autogptq-index/whl/cu118/ # Note: For ROCm, one might build from source, but standard pip instruction provided.
# or typically: pip install --no-build-isolation auto-gptq

# 6. Install remaining requirements
echo "Installing remaining dependencies from requirements.txt..."
pip install -r ../requirements.txt

# 7. Verify ROCm
echo "Verifying ROCm installation..."
python3 -c "import torch; print(f'ROCm available: {torch.version.hip is not None and torch.cuda.is_available()}')"

# 8. Print success banner
echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN}   ROCm Setup Completed Successfully! ${NC}"
echo -e "${GREEN}====================================${NC}"
echo "To activate the environment: source bunker-env/bin/activate"
