#!/bin/bash
# Super Desktop Assistant - 一键部署 (Linux/macOS/WSL)
set -e

echo "=== Super Desktop Assistant 部署 ==="

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "❌ 需要 Python 3.10+ https://python.org"
    exit 1
fi

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    echo ">>> 创建虚拟环境..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# 安装依赖
echo ">>> 安装依赖..."
pip install -r requirements.txt -q

# 配置检查
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  已创建 .env，请编辑填入 API Key 后重新运行"
    echo ""
    echo "    至少需要填一个 LLM 供应商的 Key（如 DEEPSEEK_API_KEY）"
    echo "    填好后重新运行本脚本完成部署"
    exit 1
fi

# 检查是否还是默认占位符
if grep -q "sk-your-key-here\|your-key-here\|your-mimo-key" .env 2>/dev/null; then
    echo "⚠️  .env 中仍有占位符，请编辑填入真实 API Key 后重新运行"
    echo ""
    echo "    nano .env"
    echo ""
    echo "    至少需要填一个 LLM 供应商的 Key（如 DEEPSEEK_API_KEY）"
    exit 1
fi

echo "✅ 部署完成！"
echo ""
echo "启动方式:"
echo "  Web UI:  python app.py --web"
echo "  CLI:     python app.py --cli"
echo "  Docker:  docker compose up -d"
