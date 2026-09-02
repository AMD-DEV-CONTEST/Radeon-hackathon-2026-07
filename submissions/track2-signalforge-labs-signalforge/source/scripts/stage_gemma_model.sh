#!/usr/bin/env bash
set -euo pipefail

repository="google/gemma-4-26B-A4B-it-qat-q4_0-gguf"
revision="d1c082be9cf3c8a514acf63b8761f4b41935842e"
filename="gemma-4-26B_q4_0-it.gguf"
expected_sha256="3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d"
destination="${1:-models/gemma4-26b-q4}"

if [[ "${SIGNALFORGE_ACCEPT_GEMMA_LICENSE:-}" != "yes" ]]; then
  echo "Set SIGNALFORGE_ACCEPT_GEMMA_LICENSE=yes only after accepting the upstream Gemma license." >&2
  exit 1
fi
if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "HF_TOKEN is required in the current process environment and is never written by this script." >&2
  exit 1
fi
command -v hf >/dev/null 2>&1 || {
  echo "Install the current Hugging Face CLI before staging the model." >&2
  exit 1
}

mkdir -p "$destination"
chmod 700 "$destination"
hf download "$repository" \
  --revision "$revision" \
  --include "$filename" \
  --local-dir "$destination"

model="$destination/$filename"
actual_sha256="$(sha256sum "$model" | awk '{print $1}')"
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
  echo "Model SHA-256 mismatch. The staged file was not accepted." >&2
  exit 1
fi
chmod 400 "$model"
echo "Verified model staged at $model"
