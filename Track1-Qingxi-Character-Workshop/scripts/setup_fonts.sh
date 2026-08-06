#!/usr/bin/env bash
# Ensure a CJK-capable font exists for card rendering.
set -euo pipefail
cd "$(dirname "$0")/.."
FONT_DIR="assets/fonts"
mkdir -p "$FONT_DIR"

have_cjk() {
  python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from src.card_compose import has_cjk_font
sys.exit(0 if has_cjk_font() else 1)
PY
}

if have_cjk; then
  echo "CJK font already available"
  exit 0
fi

echo "No CJK font found. Trying apt fonts-noto-cjk..."
if command -v apt-get >/dev/null 2>&1; then
  (sudo apt-get update && sudo apt-get install -y fonts-noto-cjk) || true
  if have_cjk; then echo "installed via apt"; exit 0; fi
fi

echo "Downloading Noto Sans SC (OFL) into $FONT_DIR ..."
URL="https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf"
DEST="$FONT_DIR/NotoSansCJKsc-Regular.otf"
if [ ! -s "$DEST" ]; then
  curl -fL --retry 2 -o "$DEST" "$URL" || wget -O "$DEST" "$URL"
fi
have_cjk && echo "font ready: $DEST" || { echo "FONT SETUP FAILED"; exit 1; }