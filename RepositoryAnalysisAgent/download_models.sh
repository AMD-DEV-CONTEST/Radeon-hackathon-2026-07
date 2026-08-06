#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-./models}"
MIRROR="${MIRROR:-modelscope}"
mkdir -p "$MODEL_DIR"

download_ms() {
    local repo=$1
    local dest=$2
    echo "  [ModelScope] $repo"
    python3 -c "
from modelscope import snapshot_download
snapshot_download('$repo', local_dir='$dest')
print('Done: $dest')
"
}

download_hf() {
    local repo=$1
    local dest=$2
    export HF_ENDPOINT=https://hf-mirror.com
    echo "  [HF Mirror] $repo"
    if command -v hf &>/dev/null; then
        hf download "$repo" --local-dir "$dest"
    elif command -v huggingface-cli &>/dev/null; then
        huggingface-cli download "$repo" --local-dir "$dest"
    fi
}

download() {
    local repo=$1; local dest=$2
    if [ "$MIRROR" = "modelscope" ]; then
        download_ms "$repo" "$dest" || { echo "ModelScope failed, trying HF mirror..."; download_hf "$repo" "$dest"; }
    else
        download_hf "$repo" "$dest"
    fi
}

echo "Source: $MIRROR"
echo ""

case "${1:-all}" in
    --rag-only)
        echo "=== bge-m3 (~2.4GB) ==="
        download BAAI/bge-m3 "$MODEL_DIR/bge-m3"
        echo "=== bge-reranker-v2-m3 (~0.6GB) ==="
        download BAAI/bge-reranker-v2-m3 "$MODEL_DIR/bge-reranker-v2-m3"
        ;;
    --llm-only)
        echo "=== Qwen2.5-Coder-14B-Instruct (~28GB) ==="
        download Qwen/Qwen2.5-Coder-14B-Instruct "$MODEL_DIR/Qwen2.5-Coder-14B-Instruct"
        ;;
    all|"")
        echo "=== bge-m3 (~2.4GB) ==="
        download BAAI/bge-m3 "$MODEL_DIR/bge-m3"
        echo "=== bge-reranker-v2-m3 (~0.6GB) ==="
        download BAAI/bge-reranker-v2-m3 "$MODEL_DIR/bge-reranker-v2-m3"
        echo "=== Qwen2.5-Coder-14B-Instruct (~28GB) ==="
        download Qwen/Qwen2.5-Coder-14B-Instruct "$MODEL_DIR/Qwen2.5-Coder-14B-Instruct"
        ;;
    *) echo "Usage: bash download_models.sh [--llm-only|--rag-only]"; exit 1 ;;
esac

echo ""
echo "=== Done. Models in $MODEL_DIR/ ==="
