#!/bin/bash
set -e

echo "=========================================="
echo "  断脉 AI 漫剧工作台 - 一键部署脚本 (v3 Final)"
echo "=========================================="

# 1. 激活虚拟环境
echo "[1/7] 激活 Python 虚拟环境..."
source /opt/venv/bin/activate

# 2. 修复 DNS 并安装系统工具
echo "[2/7] 修复 DNS 并安装缺失工具 (tmux, nano 等)..."
echo "nameserver 8.8.8.8" | tee /etc/resolv.conf > /dev/null
echo "nameserver 114.114.114.114" | tee -a /etc/resolv.conf > /dev/null
apt-get update -qq
apt-get install -y tmux nano htop bc jq unzip net-tools aria2 > /dev/null

# 3. 安装 Python 依赖
echo "[3/7] 安装 Python 依赖 (modelscope, streamlit)..."
pip install -q modelscope streamlit requests

# 4. 目录与持久化配置
echo "[4/7] 配置持久化存储目录..."
mkdir -p /persistent
[ -d "/persistent" ] && [ ! -L "/workspace/persistent" ] && ln -sfn /persistent /workspace/persistent
mkdir -p /workspace/duanmai

# 5. 下载模型
echo "[5/7] 下载 Qwen3.6-35B-A3B 模型 (约 35GB)..."
cd /persistent
if [ ! -f "/persistent/models/Qwen3.6-35B-A3B-Q8_0.gguf" ]; then
    modelscope download --model zhifu31588/llama-qwen3.6-A3B models/Qwen3.6-35B-A3B-Q8_0.gguf --local_dir /persistent
else
    echo "模型已存在，跳过下载。"
fi

# 6. 编译 llama.cpp (解决 npm/HF 网络问题)
echo "[6/7] 编译 llama.cpp (AMD ROCm HIP 后端)..."
cd /workspace/duanmai
[ ! -d "llama.cpp" ] && git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp

# 核心修复：配置国内镜像 + 防卡死双保险
npm config set registry https://registry.npmmirror.com
export HF_ENDPOINT=https://hf-mirror.com
mkdir -p tools/server/public
echo "<html><body>Duanmai API</body></html>" > tools/server/public/index.html

cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS="gfx1100" -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j 16

# 7. 部署 WebUI 代码
echo "[7/7] 部署 Streamlit WebUI..."
cd /workspace/duanmai

# 7. 部署 WebUI 代码（app.py 随仓库提供）
echo "[7/7] 部署 Streamlit WebUI..."
cd /workspace/duanmai
[ -f app.py ] || cp /workspace/Radeon-hackathon-2026-07/duanmai-ai-screenplay-studio/app.py . 2>/dev/null || true


echo "streamlit" > requirements.txt
echo "requests" >> requirements.txt

echo ""
echo "=========================================="
echo "  🎉 setup.sh 全部执行完毕！"
echo "=========================================="
echo "接下来请运行启动脚本： bash start.sh"
