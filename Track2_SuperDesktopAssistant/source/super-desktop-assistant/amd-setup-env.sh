#!/bin/bash
# ======================================================
# AMD Hackathon — 开发环境 + 模型下载一键脚本
# 在服务器上跑: bash amd-setup-env.sh
# ======================================================
set -e

PIP="pip3 install --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple"

echo "========================================"
echo " AMD Hackathon — 环境 + 模型安装"
echo " 预计耗时: 30-60 分钟（取决于网络）"
echo "========================================"

# ---------- 1. 系统依赖 ----------
echo "[1/8] 系统依赖..."
apt-get update -qq
apt-get install -y -qq git curl wget vim htop sox libsox-dev 2>&1 | tail -1

# ---------- 2. Python 工具链 ----------
echo "[2/8] Python 工具链..."
$PIP huggingface_hub[hf_xet] modelscope 2>&1 | tail -2

# ---------- 3. ROCm PyTorch ----------
echo "[3/8] ROCm PyTorch..."
pip3 install --break-system-packages --pre torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/nightly/rocm7.0 2>&1 | tail -3

# ---------- 4. AI 框架 ----------
echo "[4/8] AI 框架..."
$PIP transformers accelerate vllm sentence-transformers diffusers 2>&1 | tail -3

# ---------- 5. Agent + RAG ----------
echo "[5/8] Agent 框架..."
$PIP langchain langchain-community chromadb 2>&1 | tail -3

# ---------- 6. 语音 ----------
echo "[6/8] 语音..."
$PIP faster-whisper openwakeword pyaudio 2>&1 | tail -3
# CosyVoice 需要从源码安装
if [ ! -d "/workspace/CosyVoice" ]; then
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /workspace/CosyVoice 2>&1 | tail -2
fi

# ---------- 7. 前端 ----------
echo "[7/8] 前端..."
$PIP gradio Pillow 2>&1 | tail -3

# ---------- 8. 下载模型 ----------
echo "[8/8] 下载模型..."
mkdir -p /workspace/models

echo "  → Qwen3-VL-30B-A3B-AWQ (~15GB)..."
HF_ENDPOINT=https://hf-mirror.com HF_XET_HIGH_PERFORMANCE=1 \
  hf download navispace/Qwen3-VL-30B-A3B-Thinking-AWQ \
  --local-dir /workspace/models/Qwen3-VL-30B-A3B-AWQ 2>&1 | tail -3

echo ""
echo "========================================"
echo " ✅ 环境 + 模型安装完成！"
echo "========================================"
python3 -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'ROCm available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB')
"
