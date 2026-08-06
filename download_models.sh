#!/bin/bash
# Download Qwen3-VL-8B-Instruct model (runs once, ~16GB)
# Tries huggingface.co first, falls back to hf-mirror.com if blocked.
# Usage: bash download_models.sh
set -e

MODEL_NAME="Qwen/Qwen3-VL-8B-Instruct"
LOCAL_DIR="models/Qwen3-VL-8B-Instruct"

echo "=== Downloading ${MODEL_NAME} ==="
echo "This will download ~16GB of model weights."
echo ""

if [ -d "venv" ]; then
    source venv/bin/activate
fi

# ---------------------------------------------------------------------------
# 0. Pick a reachable endpoint. huggingface.co is preferred (fewer surprises
#    with gated/private repos, rate limits, etc.); hf-mirror.com is the
#    fallback for networks that blackhole HF's own domain/CDN.
# ---------------------------------------------------------------------------
echo "[0/3] Checking connectivity..."
if curl -sS --max-time 8 -o /dev/null https://huggingface.co 2>/dev/null; then
    export HF_ENDPOINT="https://huggingface.co"
    echo "  Using huggingface.co"
elif curl -sS --max-time 8 -o /dev/null https://hf-mirror.com 2>/dev/null; then
    export HF_ENDPOINT="https://hf-mirror.com"
    # Xet's CAS reconstruction talks directly to xethub.hf.co, bypassing the
    # mirror entirely -- that direct call 401s / hangs on this network.
    # Disabling Xet forces the classic LFS-over-HTTP path, which the mirror
    # DOES fully proxy.
    export HF_HUB_DISABLE_XET=1
    echo "  huggingface.co unreachable -- falling back to hf-mirror.com (Xet disabled, using legacy LFS path)"
else
    echo ""
    echo "  FATAL: neither huggingface.co nor hf-mirror.com is reachable."
    echo "  This is a network/egress problem -- see prior diagnostics"
    echo "  (proxy env vars, firewall/allowlist, or transfer weights in manually)."
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Ensure CLI + hf_transfer are present
# ---------------------------------------------------------------------------
echo "[1/3] Ensuring hf CLI + hf_transfer are installed..."
pip install -q -U huggingface_hub
export HF_XET_HIGH_PERFORMANCE=1
export HF_HUB_DOWNLOAD_TIMEOUT=60

# ---------------------------------------------------------------------------
# 2. Download with retries -- safe to re-run, resumes rather than restarts.
# ---------------------------------------------------------------------------
echo "[2/3] Downloading ${MODEL_NAME} via ${HF_ENDPOINT} to ${LOCAL_DIR}/..."
mkdir -p "$LOCAL_DIR"

MAX_ATTEMPTS=5
attempt=1
until hf download "$MODEL_NAME" --local-dir "$LOCAL_DIR"; do
    if [ $attempt -ge $MAX_ATTEMPTS ]; then
        echo "  FATAL: download failed after ${MAX_ATTEMPTS} attempts via ${HF_ENDPOINT}."
        echo "  Re-run this script to resume -- completed files are kept in ${LOCAL_DIR}/"
        exit 1
    fi
    echo "  Attempt ${attempt}/${MAX_ATTEMPTS} failed, retrying in 5s (resuming, not restarting)..."
    attempt=$((attempt + 1))
    sleep 5
done
echo "  Download complete."

# ---------------------------------------------------------------------------
# 3. Verify from local disk (no network needed here)
# ---------------------------------------------------------------------------
echo "[3/3] Verifying the downloaded weights load correctly..."
python3 -c "
from transformers import AutoProcessor, AutoModelForImageTextToText
import torch

local_dir = '${LOCAL_DIR}'
print('Loading processor from local dir (offline)...')
AutoProcessor.from_pretrained(local_dir, local_files_only=True)

print('Loading model from local dir (offline)...')
AutoModelForImageTextToText.from_pretrained(
    local_dir,
    torch_dtype='auto',
    device_map='auto',
    local_files_only=True,
)
print('${MODEL_NAME} downloaded and verified successfully!')
"

echo ""
echo "=== Done ==="
echo ""
echo "To use with vLLM server:"
echo "  vllm serve ${LOCAL_DIR} --max-model-len 4096"
echo ""
echo "To use directly:"
echo "  from transformers import AutoModelForImageTextToText, AutoProcessor"
echo "  model = AutoModelForImageTextToText.from_pretrained('${LOCAL_DIR}', local_files_only=True)"