#!/usr/bin/env bash
# ============================================================
# W7 模型下载：TripoSR（单图 → 3D 重建）
# 用法: bash scripts/download_3d_model.sh
# 说明: 通过 hf-mirror.com 镜像下载，断点续传，已存在则跳过
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$PROJECT_DIR/ComfyUI/models/checkpoints/TripoSR.ckpt"
HF="${HF:-https://hf-mirror.com}"

mkdir -p "$(dirname "$DEST")"
if [ -f "$DEST" ] && [ -s "$DEST" ]; then
  echo "==> 已存在，跳过: TripoSR ($DEST)"
  exit 0
fi
echo "==> 下载 TripoSR（约 1GB）"
curl -L --retry 3 -C - -o "$DEST" "$HF/stabilityai/TripoSR/resolve/main/model.ckpt"
echo "==> 完成: $DEST"
