#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${STAGEPOSTER_ROOT:-/workspace/poster-engine}"
COMFY_ROOT="${COMFY_ROOT:-$ROOT/ComfyUI}"
VLLM_VENV="${VLLM_VENV:-$ROOT/.venv-vllm}"

QWEN_REPO="${QWEN_REPO:-Qwen/Qwen3.5-9B}"
QWEN_DIR="${QWEN_DIR:-$ROOT/models/Qwen3.5-9B}"

ZIMAGE_REPO="${ZIMAGE_REPO:-Comfy-Org/z_image_turbo}"
TMP_DIR="${MODEL_DOWNLOAD_TMP:-$ROOT/models/.downloads/z_image_turbo}"

HF_BIN="${HF_BIN:-$VLLM_VENV/bin/hf}"

if [[ ! -x "$HF_BIN" ]]; then
  echo "hf CLI not found at $HF_BIN" >&2
  echo "Run scripts/install-vllm.sh first." >&2
  exit 1
fi

mkdir -p \
  "$QWEN_DIR" \
  "$TMP_DIR" \
  "$COMFY_ROOT/models/diffusion_models" \
  "$COMFY_ROOT/models/text_encoders" \
  "$COMFY_ROOT/models/vae" \
  "$COMFY_ROOT/models/loras"

echo "Downloading Qwen3.5-9B..."

"$HF_BIN" download \
  "$QWEN_REPO" \
  --local-dir "$QWEN_DIR"

echo "Downloading Z-Image-Turbo ComfyUI files..."

"$HF_BIN" download \
  "$ZIMAGE_REPO" \
  split_files/diffusion_models/z_image_turbo_bf16.safetensors \
  split_files/text_encoders/qwen_3_4b.safetensors \
  split_files/vae/ae.safetensors \
  split_files/loras/z_image_turbo_distill_patch_lora_bf16.safetensors \
  --local-dir "$TMP_DIR"

install -m 0644 \
  "$TMP_DIR/split_files/diffusion_models/z_image_turbo_bf16.safetensors" \
  "$COMFY_ROOT/models/diffusion_models/z_image_turbo_bf16.safetensors"

install -m 0644 \
  "$TMP_DIR/split_files/text_encoders/qwen_3_4b.safetensors" \
  "$COMFY_ROOT/models/text_encoders/qwen_3_4b.safetensors"

install -m 0644 \
  "$TMP_DIR/split_files/vae/ae.safetensors" \
  "$COMFY_ROOT/models/vae/ae.safetensors"

install -m 0644 \
  "$TMP_DIR/split_files/loras/z_image_turbo_distill_patch_lora_bf16.safetensors" \
  "$COMFY_ROOT/models/loras/z_image_turbo_distill_patch_lora_bf16.safetensors"

echo
echo "Model download complete."

find \
  "$QWEN_DIR" \
  "$COMFY_ROOT/models/diffusion_models" \
  "$COMFY_ROOT/models/text_encoders" \
  "$COMFY_ROOT/models/vae" \
  "$COMFY_ROOT/models/loras" \
  -type f \
  \( -name '*.safetensors' -o -name '*.json' \) \
  -printf '%s\t%p\n' \
  | sort -n
