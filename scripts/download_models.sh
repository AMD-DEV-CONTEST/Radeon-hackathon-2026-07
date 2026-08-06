#!/usr/bin/env bash
# ============================================================
# 模型下载脚本（P1：概念原画 + 深度图）
# 用法: bash scripts/download_models.sh
# 说明: 通过 hf-mirror.com（HuggingFace 国内镜像）下载，
#       支持断点续传；重复执行会自动跳过已下载文件
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFY_DIR="$PROJECT_DIR/ComfyUI"
MODELS_DIR="$COMFY_DIR/models"

mkdir -p "$MODELS_DIR/checkpoints" "$MODELS_DIR/vae" "$MODELS_DIR/controlnet/auxiliary"

# 国内访问 HuggingFace 用镜像；海外可直接改为 https://huggingface.co
HF="${HF:-https://hf-mirror.com}"

download() {
  local url="$1"
  local dest="$2"
  local desc="$3"
  if [ -f "$dest" ] && [ -s "$dest" ]; then
    echo "==> 已存在，跳过: $desc ($dest)"
    return
  fi
  echo "==> 下载: $desc"
  curl -L --retry 3 -C - -o "$dest" "$url"
}

echo "==> 模型目录: $MODELS_DIR"

# W1 概念原画：SDXL 基座模型（约 6.9GB）
download \
  "$HF/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" \
  "$MODELS_DIR/checkpoints/sd_xl_base_1.0.safetensors" \
  "SDXL 基座模型"

# W1 官方 VAE（约 330MB）
download \
  "$HF/stabilityai/sdxl-vae/resolve/main/sdxl_vae.safetensors" \
  "$MODELS_DIR/vae/sdxl_vae.safetensors" \
  "SDXL VAE"

# W2 深度图：MiDaS DPT-Hybrid（约 87MB，controlnet_aux 自动识别的路径）
download \
  "$HF/lllyasviel/Annotators/resolve/main/dpt_hybrid-midas-501f0c75.pt" \
  "$MODELS_DIR/controlnet/auxiliary/dpt_hybrid-midas-501f0c75.pt" \
  "MiDaS 深度模型 (DPT-Hybrid)"

echo ""
echo "✅ 模型下载完成！"
echo "   模型清单详见 docs/models.md"
echo "   提示: Depth Anything V2 可选升级（见 docs/models.md）"
