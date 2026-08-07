#!/bin/bash
# ============================================================
# NodeFlow — 一键在 GPU 实例上安装并启动 ComfyUI
# 目的: 让 MiniMax H3 视频 / 高清图 / 超分修复节点变真功能
# 磁盘: 全部装到 /persistent (持久盘, 重启不丢, 约 45GB)
# 用法: bash setup_comfyui.sh
# ============================================================
set -e

echo "============================================"
echo "  ComfyUI 安装脚本 (NodeFlow 视频/超分)"
echo "  目标目录: /persistent/ComfyUI"
echo "============================================"

INSTALL_DIR=/persistent/ComfyUI
# 复用已存在的持久 venv (NodeFlow 后端已用它跑 SDXL)
VENV_DIR=/persistent/venv

# ---- 0. 检查磁盘空间 ----
echo ""
echo "[0/6] 检查 /persistent 磁盘空间..."
AVAIL=$(df --output=avail -B1G /persistent | tail -1)
echo "  /persistent 可用: ${AVAIL}G"
if [ "${AVAIL%G}" -lt 50 ]; then
  echo "  ⚠ 可用空间 < 50G, 建议清理后重试 (需约 45G)"
fi

# ---- 1. 克隆 ComfyUI ----
echo ""
echo "[1/6] 克隆 ComfyUI (原生内置 MiniMax H3 ≥0.30.0)..."
if [ ! -d "$INSTALL_DIR/.git" ]; then
  mkdir -p "$INSTALL_DIR"
  git clone https://github.com/Comfy-Org/ComfyUI.git "$INSTALL_DIR"
else
  echo "  ComfyUI 已存在, 拉取更新"
  cd "$INSTALL_DIR" && git pull
fi
cd "$INSTALL_DIR"

# ---- 2. 准备 Python 环境 (复用持久 venv) ----
echo ""
echo "[2/6] 准备 Python 环境 (复用 /persistent/venv)..."
source "$VENV_DIR/bin/activate"

# 安装 ComfyUI 依赖 (缺的才装)
pip install -r requirements.txt 2>&1 | tail -5

# 确认 torch 可用 (ROCm)
python -c "
import torch
print('  torch:', torch.__version__)
print('  CUDA 可用:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('  GPU:', torch.cuda.get_device_name(0))
"

# ---- 3. 自定义节点: KJNodes (Sage Attention 加速) ----
echo ""
echo "[3/6] 安装 KJNodes (Sage Attention 加速)..."
mkdir -p custom_nodes
if [ ! -d custom_nodes/ComfyUI-KJNodes ]; then
  git clone https://github.com/kijai/ComfyUI-KJNodes.git custom_nodes/ComfyUI-KJNodes
  pip install -r custom_nodes/ComfyUI-KJNodes/requirements.txt 2>&1 | tail -3
else
  echo "  KJNodes 已存在"
fi

# ---- 4. 下载 MiniMax H3 模型 (~39.6GB) ----
echo ""
echo "[4/6] 下载 MiniMax H3 模型 (~39.6GB, 请耐心等待)..."
pip install -U "huggingface_hub[cli]" 2>&1 | tail -2
mkdir -p models/diffusion_models models/text_encoders models/vae models/upscale_models

# 使用 HF 镜像 (实例无法直连 huggingface.co)
export HF_ENDPOINT=https://hf-mirror.com

huggingface-cli download Comfy-Org/MiniMax-H3 \
  diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
  text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
  vae/minimax_h3_video_vae_fp16.safetensors \
  vae/minimax_h3_audio_vae_fp32.safetensors \
  --local-dir models \
  || echo "  ⚠ HF 下载失败, 请检查网络/HF_TOKEN"

# ---- 5. 下载 RealESRGAN 超分模型 (64MB) ----
echo ""
echo "[5/6] 下载 RealESRGAN 超分模型..."
wget -q -O models/upscale_models/RealESRGAN_x4plus.pth \
  https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth \
  && echo "  ✓ RealESRGAN_x4plus.pth 下载完成" \
  || echo "  ⚠ RealESRGAN 下载失败"

echo ""
echo "[6/6] 完成"
echo "============================================"
echo "  ComfyUI 已就绪: $INSTALL_DIR"
echo "  模型占用:"
du -sh models/* 2>/dev/null
echo ""
echo "  现在启动 ComfyUI:"
echo "    cd $INSTALL_DIR && source $VENV_DIR/bin/activate && python main.py --port 8188"
echo ""
echo "  启动后 NodeFlow 一旦检测到 localhost:8188,"
echo "  视频/高清/超分节点将从 mock 自动切换为真实功能。"
echo "============================================"