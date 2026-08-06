#!/bin/bash
# XAI 统一操作台 · 一键启动器
# 解决「双击打不开 / 卡住」：
#   1) GUI 双击启动时没有 zshrc 环境 → 这里显式从 ~/.zshrc 解析并注入 DEEPSEEK_API_KEY
#   2) 真正拉起后端服务（server_xai.py），再开独立窗口
#   3) xai_launcher.py 会先 pkill 旧实例，避免多服务抢端口
set -e

PY=/Users/Admin/.workbuddy/binaries/python/versions/3.13.12/bin/python3
DIR=/Users/Admin/Desktop/mask/xai

# 若环境里没有 key，则从 ~/.zshrc 解析（双击启动的 GUI 环境不会自动加载）
if [ -z "$DEEPSEEK_API_KEY" ]; then
  KEY=$("$PY" "$DIR/xai_read_key.py" 2>/dev/null)
  if [ -n "$KEY" ]; then
    export DEEPSEEK_API_KEY="$KEY"
  fi
fi

cd "$DIR"
exec "$PY" xai_launcher.py
