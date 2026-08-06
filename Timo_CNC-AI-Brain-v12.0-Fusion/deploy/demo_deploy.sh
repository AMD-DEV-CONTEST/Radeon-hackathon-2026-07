#!/bin/bash
# 🦞 Union·由你 — 客户演示环境一键部署
# 用法: bash deploy_deploy.sh
# 输出: http://localhost:7861

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}🦞 Union·由你 CNC AI 工艺大脑 — 演示环境部署${NC}"
echo -e "${BLUE}============================================================${NC}"

# 1. 检查 Python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "❌ 未找到 Python3，请先安装 Python 3.10+"
    exit 1
fi
echo -e "${GREEN}✅ Python: $($PYTHON --version)${NC}"

# 2. 检查/安装 Ollama
if curl -s http://localhost:11434/api/tags &>/dev/null; then
    echo -e "${GREEN}✅ Ollama 已运行${NC}"
else
    echo -e "${YELLOW}⚠️  Ollama 未运行${NC}"
    if command -v ollama &>/dev/null; then
        echo "启动 Ollama..."
        ollama serve &
        sleep 5
    else
        echo "正在安装 Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
        sleep 3
    fi
fi

# 3. 检查/拉取模型
if curl -s http://localhost:11434/api/tags | grep -q "qwen2.5:3b"; then
    echo -e "${GREEN}✅ 模型 qwen2.5:3b 已就绪${NC}"
else
    echo -e "${YELLOW}拉取模型 qwen2.5:3b (首次约需 2-3 分钟)...${NC}"
    ollama pull qwen2.5:3b
fi

# 4. 安装 Python 依赖
echo "安装依赖..."
$PYTHON -m pip install -q fastapi "uvicorn>=0.20" -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null || \
$PYTHON -m pip install -q fastapi "uvicorn>=0.20"

# 5. 检查 quote-ptuning 引擎
QUOTE_SKILL="$HOME/.openclaw/skills/quote-ptuning/scripts/quote.py"
if [ -f "$QUOTE_SKILL" ]; then
    echo -e "${GREEN}✅ quote-ptuning 报价引擎已就绪${NC}"
else
    echo -e "${YELLOW}⚠️  quote-ptuning 未安装，报价将使用 LLM 估算${NC}"
fi

# 6. 启动
echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}🚀 启动 CNC AI 工艺大脑...${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""
echo -e "  访问地址: ${GREEN}http://localhost:7861${NC}"
echo -e "  API 文档: ${GREEN}http://localhost:7861/api/status${NC}"
echo ""
echo "  试试输入:"
echo "    • 6061铝合金法兰 50件 阳极氧化 报价"
echo "    • 钛合金TC4叶轮 20件 IT5精度 能接吗"
echo "    • 304不锈钢轴套 200个 镀镍 报价"
echo ""
echo "  按 Ctrl+C 停止"
echo ""

# 选择合适的 Python 启动方式
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# 尝试 conda 环境
if [ -f "$HOME/.miniconda/envs/forge_v7/bin/python" ]; then
    "$HOME/.miniconda/envs/forge_v7/bin/python" app/main.py
else
    $PYTHON app/main.py
fi
