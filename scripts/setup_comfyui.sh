#!/usr/bin/env bash
# ============================================================
# ComfyUI 一键安装脚本（P1）
# 用法: bash scripts/setup_comfyui.sh
# 功能: 克隆 ComfyUI、创建虚拟环境、安装依赖与自定义节点
# 说明: 自动检测 GPU —— NVIDIA 装 CUDA 版 / AMD 装 ROCm 版 / 无 GPU 装 CPU 版
#       三个分支均固定 torch/torchvision/torchaudio 配套版本，避免 ABI 不兼容
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFY_DIR="$PROJECT_DIR/ComfyUI"

echo "==> 项目目录: $PROJECT_DIR"

# 1. 克隆 ComfyUI（已存在则跳过）
if [ ! -d "$COMFY_DIR/.git" ]; then
  echo "==> 克隆 ComfyUI ..."
  git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFY_DIR"
else
  echo "==> ComfyUI 已存在，跳过克隆"
fi

cd "$COMFY_DIR"

# 2. 创建虚拟环境
if [ ! -d ".venv" ]; then
  echo "==> 创建 Python 虚拟环境 .venv ..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip -q

# 3. 安装 PyTorch（按 GPU 类型自动选择）
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "==> 检测到 NVIDIA GPU，安装 CUDA 版 PyTorch (cu128) ..."
  pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 torchaudio==2.11.0+cu128 \
    --index-url https://download.pytorch.org/whl/cu128
elif [ -e /dev/kfd ] || command -v rocminfo >/dev/null 2>&1; then
  echo "==> 检测到 AMD GPU，安装 ROCm 版 PyTorch (rocm7.1) ..."
  pip install torch==2.11.0+rocm7.1 torchvision==0.26.0+rocm7.1 torchaudio==2.11.0+rocm7.1 \
    --index-url https://download.pytorch.org/whl/rocm7.1
else
  echo "==> 未检测到 GPU，安装 CPU 版 PyTorch ..."
  pip install torch==2.11.0+cpu torchvision==0.26.0+cpu torchaudio==2.11.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu
fi

# 4. 安装 ComfyUI 依赖
echo "==> 安装 ComfyUI 依赖 ..."
pip install -r requirements.txt

# 5. 安装自定义节点（P1：深度图工作流所需）
mkdir -p custom_nodes
install_node() {
  local name="$1"
  local url="$2"
  if [ ! -d "custom_nodes/$name" ]; then
    echo "==> 安装自定义节点: $name"
    git clone --depth 1 "$url" "custom_nodes/$name"
    if [ -f "custom_nodes/$name/requirements.txt" ]; then
      pip install -r "custom_nodes/$name/requirements.txt"
    fi
  else
    echo "==> 自定义节点已存在: $name"
  fi
}
install_node ComfyUI-DepthAnythingV2 https://github.com/kijai/ComfyUI-DepthAnythingV2.git
install_node comfyui_controlnet_aux https://github.com/Fannovel16/comfyui_controlnet_aux.git
# 项目自带节点（P3：PBR/音乐/音效）
ln -sfn "$PROJECT_DIR/nodes/indie_studio_nodes" custom_nodes/indie_studio_nodes

# 6. 创建模型目录
echo "==> 创建模型目录 ..."
mkdir -p models/checkpoints models/vae models/controlnet/auxiliary models/depthanything models/loras

# 7. 让 HuggingFace 下载走国内镜像（hf-mirror）
if ! grep -q "HF_ENDPOINT" "$COMFY_DIR/.venv/bin/activate" 2>/dev/null; then
  echo "export HF_ENDPOINT=https://hf-mirror.com" >> "$COMFY_DIR/.venv/bin/activate"
fi

echo ""
echo "✅ ComfyUI 安装完成！"
echo "   启动: cd $COMFY_DIR && .venv/bin/python main.py --listen 0.0.0.0 --port 8188"
echo "   浏览器: http://localhost:8188"
echo "   下一步: bash scripts/download_models.sh"
