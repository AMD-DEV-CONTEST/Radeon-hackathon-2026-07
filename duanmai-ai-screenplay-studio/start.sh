#!/bin/bash
source /opt/venv/bin/activate

echo "🧹 正在清理所有相关旧进程..."
tmux kill-session -t duanmai 2>/dev/null || true
pkill -9 -f llama-server 2>/dev/null || true
pkill -9 -f streamlit 2>/dev/null || true
pkill -9 -f cloudflared 2>/dev/null || true
sleep 2
echo "✅ 旧进程已清理完毕。"

# ==========================================
# 1. 启动 llama-server
# ==========================================
echo "🚀 正在启动 llama-server (32K上下文 / 并发2 / 思考模式)..."
tmux new-session -d -s duanmai -n llama
tmux send-keys -t duanmai:llama "/workspace/duanmai/llama.cpp/build/bin/llama-server \
-m /persistent/models/Qwen3.6-35B-A3B-Q8_0.gguf \
--host 127.0.0.1 --port 8000 \
-ngl 999 \
-c 32768 \
--parallel 1 \
--threads 16 \
--flash-attn on \
--cache-type-k q8_0 --cache-type-v q8_0 \
-b 1024 -ub 512 \
--jinja \
--reasoning-format deepseek \
--no-mmap | tee /workspace/duanmai/llama.log" C-m

echo "⏳ 正在将 35GB 模型加载到 W7900 显存，智能检测中..."
LLAMA_OK=false
for i in {1..90}; do
    if curl -s http://127.0.0.1:8000/v1/models > /dev/null 2>&1; then
        LLAMA_OK=true
        break
    fi
    sleep 2
done

# ==========================================
# 2. 启动 Streamlit WebUI
# ==========================================
echo "🎨 正在启动 Streamlit WebUI..."
tmux new-window -t duanmai -n webui
tmux send-keys -t duanmai:webui "cd /workspace/duanmai && streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true" C-m

echo "⏳ 等待 WebUI 启动..."
sleep 5
WEBUI_OK=false
if curl -s http://127.0.0.1:8501 > /dev/null 2>&1; then
    WEBUI_OK=true
fi

# ==========================================
# 3. 一键内网穿透
# ==========================================
cd /workspace
TUNNEL_URL=""
if [ ! -f "cloudflared" ]; then
    echo "⬇️ 尝试下载 cloudflared 穿透工具..."
    wget -q --show-progress https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
    if [ -f "cloudflared" ]; then
        chmod +x cloudflared
    else
        echo "⚠️ cloudflared 下载失败，跳过穿透。"
    fi
fi

if [ -f "cloudflared" ]; then
    > cloudflared.log
    nohup ./cloudflared tunnel --url http://localhost:8501 > cloudflared.log 2>&1 &
    echo "⏳ 正在生成公网访问链接..."
    sleep 8
    TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' cloudflared.log | head -1)
fi

# ==========================================
# 4. 最终状态检测
# ==========================================
echo ""
echo "=========================================="
echo "  📊 服务启动状态检测 (Performance Edition)"
echo "=========================================="
if [ "$LLAMA_OK" = true ]; then
    echo "  ✅ llama-server (LLM) : 运行中 (32K ctx / 并发2 / 思考模式)"
else
    echo "  ❌ llama-server (LLM) : 启动失败或超时！"
    echo "  👉 请执行: tail -n 30 /workspace/duanmai/llama.log 查看报错"
fi

if [ "$WEBUI_OK" = true ]; then
    echo "  ✅ Streamlit WebUI    : 运行中 (端口 8501)"
else
    echo "  ❌ Streamlit WebUI    : 启动失败"
fi

if [ -n "$TUNNEL_URL" ]; then
    echo "  ✅ Cloudflare Tunnel  : 已连接"
else
    echo "  ⚠️ Cloudflare Tunnel  : 未连接"
fi

echo "=========================================="
if [ -n "$TUNNEL_URL" ]; then
    echo "  🌍 公网访问地址:"
    echo "  👉 $TUNNEL_URL"
fi
echo "=========================================="
echo "  💡 快捷操作提示："
echo "  - 进入后台终端: tmux attach -t duanmai"
echo "  - 切换窗口: Ctrl+B 然后按 0(llama) 或 1(webui)"
echo "  - 退出终端视图: Ctrl+B 然后按 D"
echo "=========================================="
#   启动 
# chmod +x start.sh
#./start.sh