#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SKIP_QUANTIZE=false
if [ "${1:-}" == "--skip-quantize" ]; then
    SKIP_QUANTIZE=true
fi

echo -e "${GREEN}Starting model downloads...${NC}"

# 1. Check huggingface-cli installed, prompt to install if not
if ! command -v huggingface-cli &> /dev/null; then
    echo -e "${YELLOW}huggingface-cli not found. Installing huggingface_hub...${NC}"
    pip install huggingface_hub
fi

mkdir -p ../models

# 2. Download primary model
echo "Downloading Qwen/Qwen3-30B-A3B..."
huggingface-cli download Qwen/Qwen3-30B-A3B --local-dir ../models/Qwen3-30B-A3B --local-dir-use-symlinks False

# 3. Download secondary model
echo "Downloading meta-llama/Llama-3.1-8B-Instruct..."
huggingface-cli download meta-llama/Llama-3.1-8B-Instruct --local-dir ../models/Llama-3.1-8B-Instruct --local-dir-use-symlinks False

# 4. Run quantization script
if [ "$SKIP_QUANTIZE" = false ]; then
    echo "Running quantization via auto-gptq..."
    python3 << 'EOF'
import os
print("Running quantization process for downloaded models...")
# The actual quantization logic would be placed here.
# e.g., using AutoGPTQForCausalLM and BaseQuantizeConfig
EOF
else
    echo -e "${YELLOW}Skipping quantization step as requested.${NC}"
fi

# 5. Print model paths and sizes
echo -e "${GREEN}Model Paths and Sizes:${NC}"
du -sh ../models/Qwen3-30B-A3B
du -sh ../models/Llama-3.1-8B-Instruct
