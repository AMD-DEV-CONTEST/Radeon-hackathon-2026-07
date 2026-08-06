#!/usr/bin/env bash
# setup_whisper.sh — download the whisper.cpp Vulkan server + a model.
#
# This script is self-contained: everything is stored under models/whisper
# inside the project. It downloads:
#   * a prebuilt whisper.cpp Vulkan binary release
#   * the ggml-large-v3-turbo-q5_0 model
#
# Run from the project root:
#     ./scripts/setup_whisper.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$HERE/.."
DEST="$ROOT/models/whisper"
mkdir -p "$DEST"

WHISPER_VERSION="v1.8.4"
WHISPER_TARBALL="whisper-${WHISPER_VERSION}-linux-vulkan-x86_64.tar.gz"
WHISPER_URL="https://github.com/lemonade-sdk/whisper.cpp-rocm/releases/download/${WHISPER_VERSION}/${WHISPER_TARBALL}"

MODEL="ggml-large-v3-turbo-q5_0"
MODEL_BIN="${MODEL}.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${MODEL_BIN}"

echo "==> Downloading whisper.cpp server (${WHISPER_VERSION})"
if [ ! -f "$DEST/$WHISPER_TARBALL" ]; then
  curl -L --output "$DEST/$WHISPER_TARBALL" "$WHISPER_URL"
else
  echo "    tarball already present"
fi

echo "==> Extracting server"
tar -xzf "$DEST/$WHISPER_TARBALL" -C "$DEST"

echo "==> Downloading model (${MODEL})"
if [ ! -f "$DEST/$MODEL_BIN" ]; then
  curl -L --output "$DEST/$MODEL_BIN" "$MODEL_URL"
else
  echo "    model already present"
fi

echo
echo "Setup complete. Start the server with:"
echo "    ./scripts/serve_whisper.sh"
