#!/bin/bash
export PATH="$HOME/.local/bin:$PATH"
# 清理旧隧道
rc-tunnel stop
pkill -f frpc 2>/dev/null
# 后台启动ComfyUI
cd /workspace/ComfyUI
nohup ./run_comfy.sh > comfyui.log 2>&1 &
sleep 3
# 开启8188端口外网隧道
nohup rc-tunnel expose --port 8188 > tunnel.log 2>&1 &
sleep 4
echo "=========================================="
echo "✅ 你的ComfyUI外网访问HTTPS链接："
rc-tunnel status
echo "=========================================="
echo "提示：复制链接，直接在你本地浏览器打开！"
