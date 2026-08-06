#!/bin/bash
# scripts/download_models.sh — download all models to the ./models/ directory
#
# Usage:
#   bash scripts/download_models.sh
#
# Network selection:
#   Defaults to HuggingFace. Set USE_MODELSCOPE=1 when the domestic (China) network is unstable.
#   USE_MODELSCOPE=1 bash scripts/download_models.sh
#
# Quantization:
#   After downloading, automatically runs GPTQ-Int4 local quantization (Qwen3 official has not released a pre-quantized version)
#   Set SKIP_QUANTIZE=1 to skip quantization
#   SKIP_QUANTIZE=1 bash scripts/download_models.sh
set -e

mkdir -p ./models

USE_MODELSCOPE="${USE_MODELSCOPE:-0}"
SKIP_QUANTIZE="${SKIP_QUANTIZE:-0}"

# record the number of failed downloads
FAILED_COUNT=0
FAILED_MODELS=""

# list of directly downloadable models
# format: "REPO_ID|LOCAL_DIR|EXCLUDE_PATTERN"
# EXCLUDE_PATTERN: file patterns to exclude (comma-separated), leave empty to exclude none
# note: Qwen3 official has not released a GPTQ-Int4 pre-quantized version; download FP16 and quantize locally
DOWNLOAD_MODELS=(
    "Qwen/Qwen3-8B|./models/Qwen3-8B|"
    "BAAI/bge-m3|./models/bge-m3|*.DS_Store,imgs/*"
    "BAAI/bge-reranker-base|./models/bge-reranker-base|*.DS_Store,imgs/*"
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B|./models/DeepSeek-R1-Distill-Qwen-7B|"
)

# model download function (with error handling)
download_model() {
    local repo_id="$1"
    local local_dir="$2"
    local exclude_pattern="$3"
    local status=0

    echo "=== downloading $repo_id ==="

    if [ "$USE_MODELSCOPE" = "1" ]; then
        modelscope download --model "$repo_id" --local_dir "$local_dir" || status=$?
    else
        # build the exclude arguments
        local exclude_args=""
        if [ -n "$exclude_pattern" ]; then
            # convert comma-separated to multiple --exclude
            IFS=',' read -ra PATTERNS <<< "$exclude_pattern"
            for pattern in "${PATTERNS[@]}"; do
                exclude_args="$exclude_args --exclude \"$pattern\""
            done
        fi

        # run the download (eval is used to resolve quotes in the exclude arguments)
        if [ -n "$exclude_args" ]; then
            eval "$HF_CMD download \"$repo_id\" --local-dir \"$local_dir\" $exclude_args" || status=$?
        else
            $HF_CMD download "$repo_id" --local-dir "$local_dir" || status=$?
        fi
    fi

    if [ $status -ne 0 ]; then
        echo "Warning: $repo_id download failed (exit code: $status), skipping this model"
        FAILED_COUNT=$((FAILED_COUNT + 1))
        FAILED_MODELS="$FAILED_MODELS $repo_id"
        return 1
    else
        echo "✓ $repo_id downloaded successfully"
        return 0
    fi
}

if [ "$USE_MODELSCOPE" = "1" ]; then
    echo "=== downloading via ModelScope (recommended for the domestic network) ==="
    pip install -q modelscope

    for entry in "${DOWNLOAD_MODELS[@]}"; do
        IFS='|' read -r REPO_ID LOCAL_DIR EXCLUDE <<< "$entry"
        download_model "$REPO_ID" "$LOCAL_DIR" ""  # ModelScope does not need exclude
    done
else
    echo "=== downloading via HuggingFace ==="
    pip install -q huggingface-hub

    # detect the available download command
    if command -v hf &> /dev/null; then
        HF_CMD="hf"
        echo "using the new command: hf"
    elif command -v huggingface-cli &> /dev/null; then
        HF_CMD="huggingface-cli"
        echo "Warning: huggingface-cli is deprecated; upgrade huggingface-hub and use hf instead"
        echo "  upgrade command: pip install -U huggingface-hub"
    else
        echo "Error: neither hf nor huggingface-cli found; please install huggingface-hub first"
        exit 1
    fi

    # check whether an HF token is configured (for private repos or rate limits)
    if [ -z "$HF_TOKEN" ] && [ -z "$HUGGING_FACE_HUB_TOKEN" ]; then
        echo "Hint: HF_TOKEN is not set. If you hit download limits, you can set a token:"
        echo "  export HF_TOKEN=hf_xxxxxx  # obtain from https://huggingface.co/settings/tokens"
        echo "  or use hf auth login"
        echo ""
    fi

    for entry in "${DOWNLOAD_MODELS[@]}"; do
        IFS='|' read -r REPO_ID LOCAL_DIR EXCLUDE <<< "$entry"
        download_model "$REPO_ID" "$LOCAL_DIR" "$EXCLUDE"
    done
fi

echo ""
echo "=== downloading the Qwen3 non-thinking chat template ==="
curl -sL https://qwen.readthedocs.io/en/latest/_downloads/c101120b5bebcc2f12ec504fc93a965e/qwen3_nonthinking.jinja \
    -o ./models/qwen3_nonthinking.jinja || echo "Warning: chat template download failed"

echo ""
echo "=== model download completed ==="
ls -lh ./models/

# check whether any model failed
if [ $FAILED_COUNT -gt 0 ]; then
    echo ""
    echo "=== download failure summary ==="
    echo "Failed models ($FAILED_COUNT):$FAILED_MODELS"
    echo ""
    echo "Troubleshooting suggestions:"
    echo "  1. Network issue: set USE_MODELSCOPE=1 to use the domestic mirror"
    echo "     USE_MODELSCOPE=1 bash scripts/download_models.sh"
    echo "  2. Permission issue: set HF_TOKEN"
    echo "     export HF_TOKEN=hf_xxxxxx"
    echo "  3. Manually retry a single model:"
    echo "     hf download <repo_id> --local-dir ./models/<dir> --exclude '*.DS_Store'"
    echo ""
    # do not exit 1; allow continuing to the quantization step after partial success
fi

# GPTQ-Int4 local quantization
if [ "$SKIP_QUANTIZE" = "0" ]; then
    if [ ! -d "./models/Qwen3-8B-GPTQ-Int4" ]; then
        if [ -d "./models/Qwen3-8B" ]; then
            echo ""
            echo "=== starting GPTQ-Int4 local quantization ==="
            echo "Note: Qwen3 official has not released a GPTQ-Int4 pre-quantized version; quantize locally from FP16"
            echo "Estimated time: 10-30 minutes (depends on GPU performance)"
            echo ""
            python scripts/quantize_gptq.py \
                --source ./models/Qwen3-8B \
                --target ./models/Qwen3-8B-GPTQ-Int4 \
                --bits 4 \
                --group-size 128 \
                --calib-samples 128
        else
            echo ""
            echo "=== skipping quantization: Qwen3-8B was not downloaded successfully ==="
        fi
    else
        echo ""
        echo "=== GPTQ-Int4 quantized model already exists, skipping quantization ==="
        echo "To re-quantize, first delete it: rm -rf ./models/Qwen3-8B-GPTQ-Int4"
    fi
else
    echo ""
    echo "=== skipping GPTQ-Int4 quantization (SKIP_QUANTIZE=1) ==="
    echo "To manually quantize, run:"
    echo "  python scripts/quantize_gptq.py"
fi

echo ""
echo "=== all done ==="
ls -lh ./models/
