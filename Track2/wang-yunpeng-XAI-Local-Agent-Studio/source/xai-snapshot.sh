#!/usr/bin/env bash
# xai-snapshot.sh — 改代码前一行命令完成安全快照（git tag + 打包源码与数据）
# 用法: ./xai-snapshot.sh [备注]
# 作用: 在动任何 XAI 文件之前，给当前状态留一个可一键回滚的基线。
#       - 源码: 打 git tag + 打包整个仓库工作树（排除 .git/node_modules/dist/__pycache__）
#       - 数据: 打包 ~/.xai（排除 backups 自身，避免自包含）
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TS="$(date +%Y%m%dT%H%M%S)"
NOTE="${1:-manual}"
XAI_HOME="${XAI_HOME:-$HOME/.xai}"
BACKUP_DIR="$XAI_HOME/backups"
mkdir -p "$BACKUP_DIR"

echo "[xai-snapshot] 仓库: $REPO_DIR"
echo "[xai-snapshot] 数据: $XAI_HOME"

# 1) git tag（若处于 git 仓库）
if git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  TAG="xai-snapshot-$TS"
  if git -C "$REPO_DIR" tag "$TAG" 2>/dev/null; then
    echo "[xai-snapshot] git tag: $TAG"
  else
    echo "[xai-snapshot] git tag 跳过（已存在或无提交权限）"
  fi
else
  echo "[xai-snapshot] 非 git 仓库，跳过 tag"
fi

# 2) 源码快照（排除体积大/可重建的目录）
SRC_TAR="$BACKUP_DIR/source-$TS.tar.gz"
tar czf "$SRC_TAR" --exclude='.git' --exclude='node_modules' --exclude='dist' \
  --exclude='__pycache__' --exclude='*.pyc' -C "$REPO_DIR" .
echo "[xai-snapshot] 源码快照: $SRC_TAR ($(du -h "$SRC_TAR" | cut -f1))"

# 3) 数据快照（排除 backups 自身，避免自包含）
DATA_TAR="$BACKUP_DIR/data-$TS.tar.gz"
if [ -d "$XAI_HOME" ]; then
  tar czf "$DATA_TAR" --exclude='backups' -C "$HOME" .xai
  echo "[xai-snapshot] 数据快照: $DATA_TAR ($(du -h "$DATA_TAR" | cut -f1))"
fi

echo "[xai-snapshot] 完成 ✅  备注: $NOTE"
echo "[xai-snapshot] 恢复源码: tar xzf $SRC_TAR -C <目标目录>"
echo "[xai-snapshot] 恢复数据: tar xzf $DATA_TAR -C \$HOME"
