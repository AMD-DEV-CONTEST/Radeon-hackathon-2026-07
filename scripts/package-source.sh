#!/usr/bin/env bash
# 给工程师交接用：打「源码包」，不包含可重装依赖与大文件缓存。
#
# 用法：
#   bash scripts/package-source.sh
#   WITH_GIT=1 bash scripts/package-source.sh
#   bash scripts/package-source.sh /path/out.tgz
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$ROOT")"
NAME="$(basename "$ROOT")"
STAMP="$(date +%Y%m%d-%H%M)"
DEFAULT_OUT="$(dirname "$ROOT")/botversex-source-${STAMP}.tar.gz"
OUT="${1:-$DEFAULT_OUT}"
WITH_GIT="${WITH_GIT:-0}"

mkdir -p "$(dirname "$OUT")"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

{
  echo "${NAME}/node_modules"
  echo "${NAME}/apps/web/node_modules"
  echo "${NAME}/docs/presentations/scripts/node_modules"
  echo "${NAME}/apps/api/.venv"
  echo "${NAME}/apps/realtime/.venv"
  echo "${NAME}/apps/pi0_sidecar/.venv"
  echo "${NAME}/apps/pi0_sidecar/.bin"
  echo "${NAME}/botversex-local-agent"
  echo "${NAME}/.tmp"
  echo "${NAME}/.pnpm-store"
  echo "${NAME}/.vite"
  echo "${NAME}/apps/realtime/models"
  echo "${NAME}/apps/realtime/.piper_voices"
  echo "${NAME}/apps/realtime/training_logs"
  echo "${NAME}/apps/realtime/demos"
  echo "${NAME}/apps/realtime/datasets"
  echo "${NAME}/apps/api/training_logs"
  echo "${NAME}/botversex_dev.db"
  echo "${NAME}/apps/api/botversex_dev.db"
  echo "${NAME}/apps/realtime/botverseX_dev.db"
  echo "${NAME}/docs/presentations/slides-png"
  echo "${NAME}/docs/presentations/assets"
  if [ "$WITH_GIT" != 1 ]; then
    echo "${NAME}/.git"
  fi
} >"$TMP"

INFO="$ROOT/PACKAGE-INFO.txt"
{
  echo "BotverseX 源码包"
  echo "打包时间: $(date -Iseconds)"
  echo "工作树: $ROOT"
  if command -v git >/dev/null 2>&1 && [ -d "$ROOT/.git" ]; then
    echo "git HEAD: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo n/a)"
    echo "git 分支: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo n/a)"
    echo "状态: $(git -C "$ROOT" status -sb 2>/dev/null | head -1)"
  fi
  echo
  echo "先读使用说明："
  echo "  docs/HOW-TO-USE.md"
  echo "  README.md"
  echo
  echo "本地联调："
  echo "  bash scripts/dev-all.sh up"
  echo "  浏览器 http://127.0.0.1:5173"
} >"$INFO"

echo "[package-source] ROOT=$ROOT"
echo "[package-source] OUT=$OUT"
echo "[package-source] WITH_GIT=$WITH_GIT"
echo "[package-source] creating archive..."

(cd "$PARENT" && tar -czf "$OUT" \
  --exclude-from="$TMP" \
  --exclude="${NAME}/.env" \
  --exclude="${NAME}/.env.local" \
  --exclude="${NAME}/.env.*.local" \
  --exclude="${NAME}/**/node_modules" \
  --exclude="${NAME}/**/__pycache__" \
  --exclude="${NAME}/**/*.pyc" \
  --exclude="${NAME}/**/.DS_Store" \
  --exclude="${NAME}/docs/presentations/*.pptx" \
  "$NAME")

ls -lh "$OUT"
echo
echo "解压: tar -xzf $(basename "$OUT")"
echo "然后: cd ${NAME} && less docs/HOW-TO-USE.md"
echo "联调: bash scripts/dev-all.sh up"
