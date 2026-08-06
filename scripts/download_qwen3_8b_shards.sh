#!/usr/bin/env bash
set -euo pipefail

base="https://www.modelscope.cn/models/Qwen/Qwen3-8B/resolve/master"
out="${1:-/workspace/models/Qwen3-8B}"
mkdir -p "$out"

download() {
  local name="$1" total="$2"
  CHUNK_BYTES=250000000 /workspace/download_qwen_ranges.sh "$base/$name" "$total" "$out/$name"
}

download model-00001-of-00005.safetensors 3996250744 &
download model-00002-of-00005.safetensors 3993160032 &
download model-00003-of-00005.safetensors 3959604768 &
download model-00004-of-00005.safetensors 3187841392 &
download model-00005-of-00005.safetensors 1244659840 &
wait
echo "Qwen3-8B shard download complete"
