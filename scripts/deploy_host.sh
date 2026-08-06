#!/usr/bin/env bash
# ============================================================
# 宿主机一键部署（无 Docker / 无域名）：ComfyUI(8188) + 网页(8000)
# 用法: bash scripts/deploy_host.sh
# 说明: 幂等脚本，重复执行不会重复启动；日志在 logs/
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
mkdir -p logs

PY="$PROJECT_DIR/ComfyUI/.venv/bin/python"

# 1. 环境未安装时先安装
if [ ! -x "$PY" ]; then
  echo "==> 未检测到环境，先执行安装脚本 ..."
  bash scripts/setup_comfyui.sh
  echo "==> 模型若未下载，请执行: bash scripts/download_models.sh && bash scripts/download_musicgen.sh"
  exit 0
fi

# 2. 启动 ComfyUI（8188）
if curl -s --max-time 3 http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
  echo "==> ComfyUI 已在运行 (8188)"
else
  echo "==> 启动 ComfyUI ..."
  nohup "$PY" "$PROJECT_DIR/ComfyUI/main.py" --listen 0.0.0.0 --port 8188 --disable-auto-launch \
    >> logs/comfyui.log 2>&1 &
  echo "    日志: logs/comfyui.log"
fi

# 3. 启动网页（8000）
if curl -s --max-time 3 http://127.0.0.1:8000/api/workflows >/dev/null 2>&1; then
  echo "==> 网页服务已在运行 (8000)"
else
  echo "==> 启动网页服务 ..."
  nohup "$PY" -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000 \
    >> logs/web.log 2>&1 &
  echo "    日志: logs/web.log"
fi

# 4. 输出访问地址
sleep 2
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || true)
echo ""
echo "✅ 部署完成"
echo "   本机访问:  http://localhost:8000"
[ -n "$LOCAL_IP" ] && echo "   局域网访问: http://$LOCAL_IP:8000"
[ -n "$PUBLIC_IP" ] && echo "   公网访问:   http://$PUBLIC_IP:8000（需防火墙放行 8000/tcp）"
echo "   ComfyUI:   http://localhost:8188（请勿直接暴露到公网）"
