#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"

HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"

# model_id  output_subdir  remote_path  local_filename
MODELS=(
  "OpenSistemas/YOLOv8-crack-seg          yolov8-crack-seg         yolov8s/weights/best.pt  best.pt"
  "iloveass/kompon-damage-severity-detection  kompon-damage-severity   best.pt                  best.pt"
  "Decizez/yolov-corrosion-detection      yolov-corrosion          Basic_YOLO11_v1.pt       Basic_YOLO11_v1.pt"
)

download_model() {
  local repo="$1"
  local subdir="$2"
  local remote_path="$3"
  local filename="$4"
  local dest_dir="$BG_MODELS/vision/$subdir"
  local dest="$dest_dir/$filename"
  local url="$HF_MIRROR/$repo/resolve/main/$remote_path"

  mkdir -p "$dest_dir"

  if [[ -f "$dest" ]]; then
    echo "EXISTS: $dest — verifying checksum..."
    local hash
    hash=$(sha256sum "$dest" | awk '{print $1}')
    echo "  SHA256: $hash"
    echo "SKIP: already present."
    return 0
  fi

  echo "DOWNLOAD: $url → $dest"
  curl --fail --location --progress-bar \
    --retry 3 --retry-delay 5 \
    -o "${dest}.tmp" "$url"
  mv "${dest}.tmp" "$dest"

  local hash
  hash=$(sha256sum "$dest" | awk '{print $1}')
  echo "  SHA256: $hash"
  echo "OK: $dest"
}

echo "=== Downloading crack/corrosion specialist models ==="
echo "Mirror: $HF_MIRROR"
echo ""

for entry in "${MODELS[@]}"; do
  read -r repo subdir remote_path filename <<< "$entry"
  download_model "$repo" "$subdir" "$remote_path" "$filename"
  echo ""
done

echo "=== Done ==="
echo ""
echo "Copy the SHA256 values above into configs/competition/vision.yaml"
echo "Then run: python -c \"from ultralytics import YOLO; m=YOLO('PATH'); print(m.names)\""
echo "to confirm yolo_class_mapping keys for each model."
