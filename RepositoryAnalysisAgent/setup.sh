#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "  RepositoryAnalysisAgent Setup"
echo "=========================================="

# 1. 激活 venv
source /opt/venv/bin/activate
echo "[1/4] venv activated: $(which python)"

# 2. 装依赖
echo "[2/4] Installing dependencies..."
pip install -q -r requirements.txt 2>&1 | tail -3

# 3. 卸载 flash-attn
echo "[3/4] Removing flash-attn..."
pip uninstall -y flash-attn flash-attn-rotary 2>/dev/null || true

# 4. 设置环境变量
echo "[4/4] Setting ROCm env vars..."
export PYTORCH_ROCM_ARCH=gfx1100
export HSA_ENABLE_SDMA=0
export AMD_SERIALIZE_KERNEL=3
export AMD_SERIALIZE_COPY=3

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "=========================================="
echo ""
echo "Run these in SEPARATE terminals (venv auto-activated):"
echo ""
echo "  Terminal 1 - vLLM:"
echo "    source /opt/venv/bin/activate"
echo "    cd /workspace/RepoAMD"
echo "    MODEL_PATH=./models/Qwen2.5-Coder-14B-Instruct bash start_llm.sh"
echo ""
echo "  Terminal 2 - RepositoryAnalysisAgent (after vLLM ready):"
echo "    source /opt/venv/bin/activate"
echo "    cd /workspace/RepoAMD"
echo "    python -m src.server /workspace/RepoAMD"
echo ""
