#!/bin/bash
# ============================================================
# NodeFlow — 环境检查脚本 (GPU 实例启动前使用)
# 检查项目文件和运行环境是否就绪
# 实际部署请使用 start.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================"
echo "  NodeFlow — 环境检查"
echo "  项目目录: $SCRIPT_DIR"
echo "============================================"
echo ""

# 检查项目文件是否存在
echo "[1] 检查项目文件..."
BACKEND_OK=false
FRONTEND_OK=false

if [ -f "$SCRIPT_DIR/backend/main.py" ]; then
    echo "  ✓ 后端代码存在: $SCRIPT_DIR/backend/"
    BACKEND_OK=true
else
    echo "  ✗ 后端代码缺失! 需要从 Git 恢复"
fi

if [ -f "$SCRIPT_DIR/frontend/package.json" ]; then
    echo "  ✓ 前端代码存在: $SCRIPT_DIR/frontend/"
    FRONTEND_OK=true
else
    echo "  ✗ 前端代码缺失! 需要从 Git 恢复"
fi

if [ -f "$SCRIPT_DIR/start.sh" ]; then
    echo "  ✓ 启动脚本存在: $SCRIPT_DIR/start.sh"
else
    echo "  ⚠ 启动脚本缺失"
fi

# 检查环境
echo ""
echo "[2] 检查运行环境..."
echo "  Python: $(python3 --version 2>&1 || echo 'not found')"
echo "  Node.js: $(node --version 2>&1 || echo 'not found')"
echo "  npm: $(npm --version 2>&1 || echo 'not found')"

if command -v rocm-smi &> /dev/null; then
    echo "  ROCm: ✓"
    rocm-smi --showproductname 2>/dev/null | grep -i "card" | head -1 || true
else
    echo "  ROCm: not in PATH (may still work via PyTorch)"
fi

if python3 -c "import torch; print(torch.cuda.is_available())" 2>/dev/null | grep -q "True"; then
    echo "  PyTorch CUDA: ✓"
    python3 -c "import torch; print(f'  GPU: {torch.cuda.get_device_name(0)}')" 2>/dev/null || true
else
    echo "  PyTorch CUDA: ✗ (need to install requirements.txt)"
fi

# 检查 HF_TOKEN
echo ""
echo "[3] 检查 HuggingFace Token..."
if [ -n "$HF_TOKEN" ] && [ "$HF_TOKEN" != "hf_YOUR_HF_TOKEN_HERE" ]; then
    echo "  ✓ HF_TOKEN 已设置: ${HF_TOKEN:0:10}..."
else
    echo "  ⚠ HF_TOKEN 未设置! gated repo 下载会失败"
    echo "    用法: export HF_TOKEN=hf_你的token && ./start.sh"
fi

echo ""
if [ "$BACKEND_OK" = true ] && [ "$FRONTEND_OK" = true ]; then
    echo "============================================"
    echo "  环境检查完成! 运行 start.sh 开始部署:"
    echo "    cd $SCRIPT_DIR"
    echo "    HF_TOKEN=hf_你的token ./start.sh"
    echo "============================================"
else
    echo "============================================"
    echo "  部分文件缺失! 请从 Git 克隆项目:"
    echo "    cd /workspace"
    echo "    git clone https://github.com/Eason-made-it/Radeon-hackathon-2026-07.git nodeflow"
    echo "    cd nodeflow"
    echo "    HF_TOKEN=hf_你的token ./start.sh"
    echo "============================================"
fi
