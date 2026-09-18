#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"

HF_MIRROR="${HF_MIRROR:-https://huggingface.co}"
MODEL_REPO="apple/MobileCLIP2-S0"
MODEL_REVISION="2ba81a63a97707b25b0f90bcfda38b48b2cbd950"
MODEL_FILE="mobileclip2_s0.pt"
EXPECTED_SHA256="bc3bc861baa680df2f9e3dc1aa0acbe5a21af21032df385026dda70c33505aa6"
DEST_DIR="$BG_MODELS/vision/mobileclip2-s0"
DEST="$DEST_DIR/$MODEL_FILE"
URL="$HF_MIRROR/$MODEL_REPO/resolve/$MODEL_REVISION/$MODEL_FILE"

mkdir -p "$DEST_DIR"

verify_model() {
  local path="$1"
  local actual
  actual=$(sha256sum "$path" | awk '{print $1}')
  if [[ "$actual" != "$EXPECTED_SHA256" ]]; then
    echo "ERROR: MobileCLIP2-S0 checksum mismatch" >&2
    echo "  expected: $EXPECTED_SHA256" >&2
    echo "  actual:   $actual" >&2
    return 1
  fi
}

if [[ -f "$DEST" ]]; then
  verify_model "$DEST"
  echo "EXISTS: verified MobileCLIP2-S0 at $DEST"
  exit 0
fi

echo "DOWNLOAD: $URL -> $DEST"
curl --fail --location --progress-bar \
  --retry 3 --retry-delay 5 \
  -o "${DEST}.tmp" "$URL"
verify_model "${DEST}.tmp"
mv "${DEST}.tmp" "$DEST"
echo "OK: verified MobileCLIP2-S0 at $DEST"
