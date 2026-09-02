#!/bin/bash
# XAI 统一操作台 - macOS 桌面启动器
# 双击此文件即可启动（首次可能需要右键→打开）

cd "$(dirname "$0")"

XAI_HOME="${HOME}/.xai"
XAI_PORT=8000
PY="${HOME}/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

echo "🚀 XAI 统一操作台 启动中..."

# 停止旧实例：基于 pid 文件精确杀掉旧 server 进程（避免 pkill -f 误杀启动器自身）
if [ -f "$XAI_HOME/server.pid" ]; then
    OLD_PID=$(cat "$XAI_HOME/server.pid" 2>/dev/null)
    if [ -n "$OLD_PID" ]; then
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
fi
rm -f "$XAI_HOME/server.pid"

# 若 GUI 双击环境没有注入 key，则从 ~/.zshrc 解析
if [ -z "$DEEPSEEK_API_KEY" ]; then
    KEY=$("$PY" "$PWD/xai_read_key.py" 2>/dev/null)
    if [ -n "$KEY" ]; then
        export DEEPSEEK_API_KEY="$KEY"
    fi
fi

# 启动后端服务
"$PY" server_xai.py &
SERVER_PID=$!
sleep 2

# 检查是否启动成功
if kill -0 $SERVER_PID 2>/dev/null; then
    echo "✅ 后端服务已启动 (PID: $SERVER_PID)"
    echo "🌐 打开浏览器 → http://localhost:${XAI_PORT}"
    sleep 1
    open "http://localhost:${XAI_PORT}"
else
    echo "❌ 后端服务启动失败"
    exit 1
fi

# 保持终端窗口，等待用户按任意键退出
echo ""
echo "按 Ctrl+C 或关闭此窗口停止服务"
wait $SERVER_PID
