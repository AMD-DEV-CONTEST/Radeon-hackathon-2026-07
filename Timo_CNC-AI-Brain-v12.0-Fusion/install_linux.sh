#!/bin/bash
# Union·由你 CNC AI Brain v11.0.2 — Linux 一键安装
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
echo -e "${CYAN}Union·由你 CNC AI 工艺大脑 v11.0.2${NC}"
echo "一键安装 (Linux)"
echo ""

# 1. 检测 Python
echo -n "[1/5] Python: "
python3 --version 2>/dev/null || { echo -e "${RED}请安装 Python 3.10+${NC}"; exit 1; }

# 2. 安装 Ollama
echo -n "[2/5] Ollama: "
if command -v ollama &>/dev/null; then
    ollama --version
else
    echo "安装中..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# 3. 拉取模型
echo "[3/5] 拉取模型 (qwen2.5:3b)..."
ollama pull qwen2.5:3b || echo "  警告: 模型拉取失败, 请在 Ollama 运行后重试"

# 4. 安装依赖
echo "[4/5] 安装依赖..."
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple -q

# 5. 启动
echo "[5/5] 完成!"
echo ""
echo "  启动: python3 app/main.py"
echo "  访问: http://localhost:7861"
echo "  仪表盘: http://localhost:7861/api/dashboard"
echo ""
echo "  systemd 自启:"
echo "  sudo cp deploy/cnc-brain.service /etc/systemd/system/"
echo "  sudo systemctl enable --now cnc-brain"
