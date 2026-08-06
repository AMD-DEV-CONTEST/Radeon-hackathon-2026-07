#!/usr/bin/env bash
# Download LoRA weights (185MB) from GitHub Release
# Required before running the Candy Chibi Sticker Generator
set -euo pipefail

WEIGHTS_DIR="src/lora/models/stkstyle_lora_diffusers"
WEIGHTS_FILE="${WEIGHTS_DIR}/pytorch_lora_weights.safetensors"
RELEASE_URL="https://github.com/kwangroy/Radeon-hackathon-2026-07/releases/download/weights-v1/pytorch_lora_weights.safetensors"

if [ -f "$WEIGHTS_FILE" ]; then
    echo "[OK] Weights already exist: $WEIGHTS_FILE"
    exit 0
fi

mkdir -p "$WEIGHTS_DIR"
echo "[Downloading] LoRA weights from GitHub Release..."
echo "  URL: $RELEASE_URL"

# Try wget first, fall back to curl
if command -v wget &>/dev/null; then
    wget -q --show-progress -O "$WEIGHTS_FILE" "$RELEASE_URL"
elif command -v curl &>/dev/null; then
    curl -L --progress-bar -o "$WEIGHTS_FILE" "$RELEASE_URL"
else
    echo "[ERROR] Neither wget nor curl is available. Please download manually:"
    echo "  $RELEASE_URL"
    echo "  -> save to $WEIGHTS_FILE"
    exit 1
fi

# Verify file size (should be ~186MB)
SIZE=$(stat -c%s "$WEIGHTS_FILE" 2>/dev/null || stat -f%z "$WEIGHTS_FILE" 2>/dev/null || echo 0)
if [ "$SIZE" -lt 100000000 ]; then
    echo "[WARNING] File size is ${SIZE} bytes, expected ~185961496. Download may be incomplete."
else
    echo "[OK] Downloaded successfully: $WEIGHTS_FILE (${SIZE} bytes)"
fi
