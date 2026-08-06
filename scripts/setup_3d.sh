#!/usr/bin/env bash
# ============================================================
# W7：2D 角色图 → 3D 模型（TripoSR）节点安装脚本
# 用法: bash scripts/setup_3d.sh
# 说明: 克隆 ComfyUI-Flowty-TripoSR 并安装依赖；
#       模型权重另用 scripts/download_3d_model.sh 下载
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PROJECT_DIR/ComfyUI/.venv/bin/python"
CUSTOM="$PROJECT_DIR/ComfyUI/custom_nodes"

if [ ! -d "$CUSTOM/ComfyUI-Flowty-TripoSR" ]; then
  echo "==> 克隆 ComfyUI-Flowty-TripoSR"
  git clone https://github.com/flowtyone/ComfyUI-Flowty-TripoSR.git "$CUSTOM/ComfyUI-Flowty-TripoSR"
fi

echo "==> 安装依赖（omegaconf / trimesh / transformers 等）"
"$VENV" -m pip install -r "$CUSTOM/ComfyUI-Flowty-TripoSR/requirements.txt"

echo "==> 修正版本兼容（ComfyUI 需要 transformers>=4.50；numpy 2 需要 trimesh>=4.5）"
"$VENV" -m pip install ${PIP_INDEX_URL:+-i "$PIP_INDEX_URL"} "transformers>=4.50.3" "trimesh>=4.5"

echo "==> 完成。下一步下载模型: bash scripts/download_3d_model.sh"
echo "    下载后重启 ComfyUI 即可在 W7 工作流中使用。"
