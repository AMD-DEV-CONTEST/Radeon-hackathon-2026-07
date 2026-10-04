#!/usr/bin/env bash
# 在 Radeon Cloud 实例（Linux + AMD GPU + ROCm）上一键安装并启动 ComfyUI
# 用法：在实例的 JupyterLab 终端或 SSH 里执行  bash setup_comfyui_rocm.sh
set -e

echo "==== 1/4 装 ROCm 版 PyTorch ===="
pip install -q torch torchvision --index-url https://download.pytorch.org/whl/rocm6.2

echo "==== 2/4 克隆 ComfyUI 并装依赖 ===="
if [ ! -d ComfyUI ]; then git clone https://github.com/comfyanonymous/ComfyUI; fi
cd ComfyUI
pip install -q -r requirements.txt

echo "==== 3/4 下载起步模型（DreamShaper 8，SD1.5，轻量，适合风格迁移）===="
mkdir -p models/checkpoints
if [ ! -f models/checkpoints/dreamshaper8.safetensors ]; then
  wget -q -O models/checkpoints/dreamshaper8.safetensors \
    "https://huggingface.co/Lykon/DreamShaper/resolve/main/DreamShaper_8.safetensors"
fi
echo "（可选）想要动漫风可再下动漫 LoRA 到 models/loras/，或在 ComfyUI 里换 SDXL 动漫模型。"

echo "==== 4/4 启动 ComfyUI（监听 0.0.0.0:8188）===="
echo "启动后，在本地 Windows 用 SSH 隧道把它映射到本机 8188："
echo "  ssh -L 8188:localhost:8188 <user>@<host> -p <port>"
echo "然后应用的 ComfyUI Base URL 保持 http://127.0.0.1:8188 即可。"
exec python main.py --listen 0.0.0.0 --port 8188
