#!/usr/bin/env bash
# Restart BotverseX on the Windows demo laptop (Reachy presentation machine).
set -euo pipefail

HOST="${DEMO_SSH_HOST:-AMD@192.168.57.233}"
KEY="${DEMO_SSH_KEY:-$HOME/.ssh/reachy_lenovo}"
SSH=(ssh -o ConnectTimeout=10)
[ -f "$KEY" ] && SSH+=(-i "$KEY")

notify-send "BotverseX" "正在重启演示机服务…" 2>/dev/null || true

"${SSH[@]}" "$HOST" "powershell -NoProfile -ExecutionPolicy Bypass -File C:/Users/AMD/dev/botversex/scripts/windows/restart-botversex.ps1" &
disown

echo "已在后台触发 Windows 演示机重启。"
echo "演示页: http://192.168.57.233:5173/robots/reachy_mini"
