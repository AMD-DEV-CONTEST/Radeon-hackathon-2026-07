#!/usr/bin/env bash
# ============================================================
# 中英翻译模型下载脚本（网页提示词中文→英文）
# 用法: bash scripts/download_translator.sh
# 说明: 离线翻译（Helsinki-NLP/opus-mt-zh-en，约 300MB），
#       断点续传，重复执行跳过已存在文件
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$PROJECT_DIR/ComfyUI/models/translator/opus-mt-zh-en"
HF="${HF:-https://hf-mirror.com}"

mkdir -p "$DEST"
echo "==> 目标目录: $DEST"

for f in config.json pytorch_model.bin source.spm target.spm vocab.json; do
  if [ -s "$DEST/$f" ]; then
    echo "==> 已存在，跳过: $f"
    continue
  fi
  echo "==> 下载: $f"
  curl -L --retry 3 -C - -o "$DEST/$f" "$HF/Helsinki-NLP/opus-mt-zh-en/resolve/main/$f"
done

echo "✅ 翻译模型下载完成"
