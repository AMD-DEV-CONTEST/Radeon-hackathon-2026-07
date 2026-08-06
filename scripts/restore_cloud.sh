#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-https://github.com/ZIFeIYUuuuuuu/Radeon-hackathon-2026-07.git}"
BRANCH="${BRANCH:-claimcourt}"
DEST="${DEST:-/workspace/claimcourt}"

if [ -e "$DEST/.git" ]; then
  git -C "$DEST" fetch origin "$BRANCH"
  git -C "$DEST" reset --hard "origin/$BRANCH"
else
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DEST"
fi

cd "$DEST"
/opt/venv/bin/python -m pip install -r requirements.txt
mkdir -p data

# Legacy .doc files are common in real desktop archives. antiword extracts
# text without opening Office or executing document macros; keep it optional
# so recovery still works on images without apt.
if ! command -v antiword >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq antiword >/dev/null 2>&1 || true
fi

echo "ClaimCourt source restored at $DEST"
echo "Start Ollama with qwen3:32b-q8_0, then run:"
echo "  /opt/venv/bin/streamlit run app.py --server.address 127.0.0.1 --server.port 8502"
