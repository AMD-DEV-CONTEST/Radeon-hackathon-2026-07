#!/usr/bin/env bash
# 无头截图：每次一个面板。用法 capture.sh <名字> <驱动JS>
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo 'usage: capture.sh <name> <driver-js>' >&2
  exit 2
fi

cd "$(dirname "$0")"
: "${SPRITE_WORKSHOP_FORCE_MOCK:=1}"
export SPRITE_WORKSHOP_FORCE_MOCK
export SW_CAPTURE_DELAY=3500
export SW_CAPTURE="${SW_CAPTURE_DIR:-/tmp/shots}/$1.png"
export SW_CAPTURE_JS="$2"
mkdir -p "$(dirname "$SW_CAPTURE")"
timeout 120 xvfb-run -a --server-args="-screen 0 1440x900x24" \
  node_modules/.bin/electron . --no-sandbox 2>&1 \
  | grep -iE "captured|renderer:error|renderer gone" | head -8
