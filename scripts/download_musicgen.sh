#!/usr/bin/env bash
# ============================================================
# MusicGen small 模型下载脚本（W4 背景音乐）
# 用法: bash scripts/download_musicgen.sh
# 说明: 通过 hf-mirror 镜像下载 facebook/musicgen-small，
#       断点续传，重复执行跳过已存在文件
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$PROJECT_DIR/ComfyUI/models/musicgen/musicgen-small"
HF="${HF:-https://hf-mirror.com}"

mkdir -p "$DEST"
echo "==> 目标目录: $DEST"

for f in config.json generation_config.json pytorch_model.bin preprocessor_config.json tokenizer.json tokenizer_config.json vocab.json; do
  if [ -s "$DEST/$f" ]; then
    echo "==> 已存在，跳过: $f"
    continue
  fi
  echo "==> 下载: $f"
  curl -L --retry 3 -C - -o "$DEST/$f" "$HF/facebook/musicgen-small/resolve/main/$f"
done

echo "✅ MusicGen 模型下载完成"
