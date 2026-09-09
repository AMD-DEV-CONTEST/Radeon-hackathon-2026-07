#!/bin/bash
# ============================================================
#  Super Desktop Assistant - Ubuntu 24.04 一键部署
#  用法: chmod +x deploy-ubuntu24.sh && ./deploy-ubuntu24.sh
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo "========================================"
echo "  Super Desktop Assistant"
echo "  Ubuntu 24.04 一键部署"
echo "========================================"
echo ""

# ─── 1. 环境检查 ───
log "检查 Python..."
PYTHON=$(which python3.12 2>/dev/null || which python3 2>/dev/null || echo "")
if [ -z "$PYTHON" ]; then
    err "未找到 Python3，请先安装: sudo apt install python3.12 python3.12-venv"
fi
PYVER=$($PYTHON --version 2>&1)
log "  $PYVER"

# ─── 2. 系统依赖 ───
log "安装系统依赖..."
sudo apt update -qq
sudo apt install -y -qq python3.12-venv python3-pip > /dev/null 2>&1 || true
log "  系统依赖 OK"

# ─── 3. 虚拟环境 ───
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    log "创建虚拟环境..."
    $PYTHON -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
log "  虚拟环境已激活"

# ─── 4. Python 依赖 ───
log "安装 Python 依赖..."
pip install --upgrade pip -q
pip install -r "$PROJECT_DIR/requirements.txt" -q
log "  依赖安装完成"

# ─── 5. 配置文件 ───
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    warn "已创建 .env 文件，请编辑填入 API Key:"
    echo ""
    echo "    nano $PROJECT_DIR/.env"
    echo ""
    echo "  至少需要填一个 LLM 供应商的 Key（如 DEEPSEEK_API_KEY）"
    echo "  填好后重新运行本脚本完成部署"
    exit 0
fi

# 检查是否还是默认占位符
if grep -q "sk-your-key-here\|your-key-here\|your-mimo-key" "$PROJECT_DIR/.env" 2>/dev/null; then
    warn ".env 中仍有占位符，请编辑填入真实 API Key 后重新运行"
    echo "    nano $PROJECT_DIR/.env"
    exit 1
fi

log "  配置文件检查通过"

# ─── 6. 数据目录 ───
mkdir -p "$PROJECT_DIR/data/conversations" "$PROJECT_DIR/outputs"
log "  数据目录已创建"

# ─── 7. systemd 服务（可选） ───
SERVICE_FILE="/etc/systemd/system/super-assistant.service"

if [ ! -f "$SERVICE_FILE" ]; then
    echo ""
    read -p "是否安装 systemd 服务（开机自启 + 后台运行）？[Y/n] " -r
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Super Desktop Assistant
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$VENV_DIR/bin/python app.py --web --host 0.0.0.0 --port 7860
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        sudo systemctl daemon-reload
        sudo systemctl enable super-assistant
        sudo systemctl start super-assistant
        log "systemd 服务已安装并启动"
        echo ""
        echo "  管理命令:"
        echo "    sudo systemctl status super-assistant  # 查看状态"
        echo "    sudo systemctl restart super-assistant # 重启"
        echo "    sudo journalctl -u super-assistant -f  # 查看日志"
    fi
fi

# ─── 8. 完成 ───
echo ""
echo "========================================"
echo "  ✅ 部署完成！"
echo "========================================"
echo ""
echo "  启动方式:"
echo "    Web UI:  source .venv/bin/activate && python app.py --web"
echo "    CLI:     source .venv/bin/activate && python app.py --cli"
echo "    Docker:  docker compose up -d"
echo ""
echo "  Web 访问: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):7860"
echo ""

# 如果是首次配置，提示
if systemctl is-active --quiet super-assistant 2>/dev/null; then
    echo "  systemd 服务状态: $(systemctl is-active super-assistant)"
fi
