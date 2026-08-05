#!/bin/bash
# Quick environment check for AMD Radeon Cloud instance (Track 2 - SOC Triage Agent)
# Usage: bash check_env.sh
# Goal: verify GPU/ROCm/vLLM readiness in <1 minute so we don't burn GPU credits debugging.

echo "===================================================="
echo " AMD Radeon GPU environment check"
echo " $(date)"
echo "===================================================="

echo -e "\n--- [1/6] OS & kernel ---"
uname -a
cat /etc/os-release 2>/dev/null | grep PRETTY_NAME

echo -e "\n--- [2/6] GPU detection (rocm-smi) ---"
if command -v rocm-smi &> /dev/null; then
    rocm-smi
else
    echo "rocm-smi NOT FOUND"
fi

echo -e "\n--- [3/6] GPU details (rocminfo) ---"
if command -v rocminfo &> /dev/null; then
    rocminfo | grep -A2 "Marketing Name" | head -20
else
    echo "rocminfo NOT FOUND"
fi

echo -e "\n--- [4/6] ROCm version ---"
if [ -f /opt/rocm/.info/version ]; then
    cat /opt/rocm/.info/version
else
    ls /opt/rocm* 2>/dev/null || echo "ROCm install path not found at /opt/rocm*"
fi

echo -e "\n--- [5/6] Python / PyTorch / vLLM ---"
python3 --version
python3 -c "import torch; print('torch:', torch.__version__); print('ROCm/HIP available:', torch.cuda.is_available()); print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')" 2>&1
python3 -c "import vllm; print('vllm:', vllm.__version__)" 2>&1

echo -e "\n--- [6/6] Disk & memory headroom ---"
df -h / 2>/dev/null | tail -1
free -h

echo -e "\n===================================================="
echo " Done. If vllm/torch import failed, install with:"
echo "   pip install vllm --extra-index-url https://download.pytorch.org/whl/rocm6.0"
echo "===================================================="
