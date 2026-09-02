#!/usr/bin/env bash
# setup.sh — 从零复现 XAI 本地运行环境（solo 私有化部署）
# 用法: ./setup.sh
# 做三件事:
#   1) 校验 Python 版本
#   2) 安装可选依赖（requirements.txt）
#   3) 构建前端（npm ci / npm install + npm run build）
# 不含: launchd 守护的安装（见底部说明，需手动执行，避免静默改写你现有 plist）
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

echo "[setup] 仓库: $REPO_DIR"
echo "[setup] Python: $($PYTHON --version 2>&1)"

# 1) 可选依赖
if [ -f "$REPO_DIR/requirements.txt" ]; then
  echo "[setup] 安装可选依赖..."
  "$PYTHON" -m pip install -r "$REPO_DIR/requirements.txt"
fi

# 2) 前端构建
if [ -d "$REPO_DIR/frontend" ]; then
  echo "[setup] 构建前端..."
  cd "$REPO_DIR/frontend"
  if [ -f package-lock.json ]; then
    npm ci
  else
    npm install
  fi
  npm run build
  cd "$REPO_DIR"
fi

# 3) 数据目录 & 日志目录
mkdir -p "$HOME/.xai/backups" "$HOME/.xai/logs"

echo ""
echo "[setup] 完成 ✅"
echo "[setup] 启动后端(开发): $PYTHON $REPO_DIR/server_xai.py"
echo "[setup] 预览前端(开发): cd $REPO_DIR/frontend && npm run dev"
echo ""
echo "[setup] 若需开机自启守护(可选，不会自动改你现有配置):"
echo "        cp $REPO_DIR/com.xai.server.plist ~/Library/LaunchAgents/"
echo "        launchctl load ~/Library/LaunchAgents/com.xai.server.plist"
echo "        # 每日自动备份同理: launchctl load ~/Library/LaunchAgents/com.xai.backup.plist"
