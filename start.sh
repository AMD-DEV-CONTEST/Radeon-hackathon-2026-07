#!/bin/bash
# ============================================================
# NodeFlow — 一键部署脚本 (GPU 实例)
# 在 AMD Radeon Cloud GPU 实例的 Terminal 里运行
# AMD Radeon GPU + Flux schnell + React/Excalidraw 前端
# ============================================================

set -e

echo "============================================"
echo "  NodeFlow — GPU 实例部署脚本"
echo "  AMD Radeon GPU + SDXL-Lightning / FLUX.2-klein"
echo "============================================"
echo ""

# ---- 配置 (自适应路径: 以脚本所在目录为项目根) ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
VENV_DIR="/persistent/venv"
BACKEND_PORT=8000

echo "  项目根目录: $PROJECT_ROOT"
echo "  后端目录:   $BACKEND_DIR"
echo "  前端目录:   $FRONTEND_DIR"

# ---- Step 1: 检查环境 ----
echo "[1/6] 检查环境..."

# 检查 ROCm
if command -v rocm-smi &> /dev/null; then
    echo "  ✓ ROCm 检测到"
    rocm-smi --showproductname 2>/dev/null | head -3 || true
else
    echo "  ⚠ 未检测到 rocm-smi, 检查 PyTorch CUDA..."
fi

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python3 未安装"
    exit 1
fi
echo "  ✓ Python: $(python3 --version)"

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "  ⚠ Node.js 未安装, 尝试安装..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi
echo "  ✓ Node.js: $(node --version)"

# ---- 环境变量: HuggingFace 镜像 + Token + 持久化缓存 ----
# 实例不能直连 huggingface.co，必须走镜像
# SDXL base + FLUX.2-klein 等 gated repo 需要 token
export HF_ENDPOINT=https://hf-mirror.com

# HF_TOKEN: 必须传入真实 token (gated repo 需要)
# 用法: HF_TOKEN=hf_xxxxx ./start.sh
if [ -z "$HF_TOKEN" ] || [ "$HF_TOKEN" = "hf_YOUR_HF_TOKEN_HERE" ]; then
    echo "  ⚠ 警告: HF_TOKEN 未设置或为占位符!"
    echo "    gated repo (FLUX.2-klein, SDXL base) 下载会失败。"
    echo "    正确用法: HF_TOKEN=hf_你的token ./start.sh"
    echo "    继续尝试, 但可能遇到 401 错误..."
fi
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
export HF_HOME=/persistent/hf_cache
mkdir -p "$HF_HOME"
echo "  ✓ HF mirror: $HF_ENDPOINT"
echo "  ✓ HF cache: $HF_HOME"
echo "  ✓ HF token: ${HF_TOKEN:0:10}..."

# ---- Step 2: 创建/激活虚拟环境 ----
echo ""
echo "[2/6] 配置 Python 虚拟环境..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "  ✓ 虚拟环境已创建: $VENV_DIR"
else
    echo "  ✓ 虚拟环境已存在: $VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# ---- Step 3: 安装后端依赖 ----
echo ""
echo "[3/6] 安装后端依赖 (FastAPI + diffusers + PyTorch)..."
cd "$BACKEND_DIR"
pip install --quiet -r requirements.txt 2>&1 | tail -5
echo "  ✓ 后端依赖安装完成"

# 验证 PyTorch + ROCm
python3 -c "
import torch
if torch.cuda.is_available():
    print(f'  ✓ PyTorch CUDA 可用 — GPU: {torch.cuda.get_device_name(0)}')
    props = torch.cuda.get_device_properties(0)
    print(f'  ✓ VRAM: {props.total_memory / 1e9:.1f} GB')
else:
    print('  ⚠ CUDA 不可用, 将使用 CPU (非常慢)')
"

# ---- Step 4: 启动后端 ----
echo ""
echo "[4/6] 启动后端 (FastAPI + SDXL-Lightning / FLUX.2-klein)..."
echo "  首次启动需要下载模型 (SDXL base ~7GB + FLUX.2-klein ~8GB), 请耐心等待..."
cd "$BACKEND_DIR"
uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT &
BACKEND_PID=$!
echo "  后端 PID: $BACKEND_PID"

# 等待后端就绪
echo "  等待 Flux 模型加载..."
for i in $(seq 1 180); do
    if curl -s http://localhost:$BACKEND_PORT/ > /dev/null 2>&1; then
        echo "  ✓ 后端就绪!"
        curl -s http://localhost:$BACKEND_PORT/api/health | python3 -m json.tool 2>/dev/null || true
        break
    fi
    sleep 3
    if [ $((i % 10)) -eq 0 ]; then
        echo "  仍在加载... ($((i*3))s)"
    fi
done

# ---- Step 5: 前端说明 ----
echo ""
echo "[5/6] 前端"
echo "  前端由后端 FastAPI 直接提供 (挂载 frontend/dist 静态文件)"
echo "  无需单独启动 Vite。访问 http://localhost:$BACKEND_PORT 即可。"

# ---- Step 5.5: 本地 ComfyUI 校验 (视频 / 高清 / 超分节点需要) ----
echo ""
echo "[5.5/6] 本地 ComfyUI"
echo "  视频生成(MiniMax H3)、高清图、超分修复节点通过前端直连本地 ComfyUI (默认 http://localhost:8188)。"
echo "  请确认 ComfyUI 已启动并安装了对应自定义节点:"
echo "    - ComfyUI_MiniMax: MiniMax H3 T2V/I2V 节点"
echo "    - ComfyUI-KJNodes: Sage Attention 加速 (PatchSageAttentionKJ)"
if curl -s --max-time 3 http://localhost:8188/system_stats > /dev/null 2>&1; then
    echo "  ✓ ComfyUI 已就绪 (localhost:8188) — 视频/高清/超分节点可用"
else
    echo "  ⚠ 未检测到 ComfyUI (localhost:8188)"
    echo "    视频/高清/超分节点将回退到 mock 占位预览。"
    echo "    如需完整功能, 请先启动 ComfyUI, 再在浏览器中访问 http://localhost:8188 确认。"
fi

# ---- Step 6: 完成 ----
echo ""
echo "[6/6] 完成"
echo ""
echo "============================================"
echo "  NodeFlow 已启动!"
echo "============================================"
echo ""
echo "  前端 + 后端: http://localhost:$BACKEND_PORT"
echo "  健康检查:     http://localhost:$BACKEND_PORT/api/health"
echo "  ComfyUI:      http://localhost:8188  (视频/高清/超分)"
echo ""
echo "  SSH 端口转发 (在本地电脑终端运行):"
echo "    ssh -L ${BACKEND_PORT}:localhost:${BACKEND_PORT} <user>@<gpu-ip>"
echo ""
echo "  然后在浏览器打开: http://localhost:${BACKEND_PORT}"
echo ""
echo "  停止服务: kill $BACKEND_PID"
echo "  或按 Ctrl+C 退出"
echo ""

# 退出时清理
trap "echo 'Shutting down...'; kill $BACKEND_PID 2>/dev/null; exit" INT TERM
wait
