#!/usr/bin/env bash
# ============================================================
# 二次元贴纸生成器 — 环境准备脚本（Linux / AMD ROCm 实例）
# 评委 / 复现者只需： git clone <repo> && cd <repo> && bash setup.sh
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "==> [1/4] 创建 Python 虚拟环境（如不存在）"
if [ ! -d venv ]; then
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

echo "==> [2/4] 安装依赖"
# 若当前 pip 默认源没有对应 ROCm wheel，取消下一行注释改用 ROCm 官方索引：
# pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.3
pip install --upgrade pip
pip install -r requirements.txt

echo "==> [3/4] 准备基座模型 SDXL (Animagine XL 4.0)"
if [ -f models/animagine-xl-4.0/model_index.json ]; then
  echo "    已就位：models/animagine-xl-4.0"
else
  echo "    未检测到，尝试从 HuggingFace 镜像下载（需联网；离线环境请手动放置到该目录）…"
  export HF_ENDPOINT="https://hf-mirror.com"
  huggingface-cli download cagliostrolab/animagine-xl-4.0 \
    --local-dir models/animagine-xl-4.0 --local-dir-use-symlinks False
fi

echo "==> [4/4] 校验随仓库分发的资产"
if [ -f src/lora/models/stkstyle_lora_diffusers/pytorch_lora_weights.safetensors ]; then
  echo "    LoRA 资产 OK：src/lora/models/stkstyle_lora_diffusers/"
else
  echo "    ⚠️ 缺少 LoRA 资产！请将 pytorch_lora_weights.safetensors 放到 src/lora/models/stkstyle_lora_diffusers/"
fi
if ls demo_output/*sticker*.png >/dev/null 2>&1; then
  echo "    Demo 成品 OK：demo_output/*sticker*.png"
else
  echo "    ⚠️ 缺少 Demo 成品！Demo 模式将不可用（仍可直接真实生成）。"
fi

echo ""
echo "✅ 准备完成。启动方式："
echo "    source venv/bin/activate"
echo "    python src/webui/gradio_app.py --port 7860"
echo "    浏览器打开 http://localhost:7860  （默认 Demo 模式，取消勾选即真实 GPU 生成）"
