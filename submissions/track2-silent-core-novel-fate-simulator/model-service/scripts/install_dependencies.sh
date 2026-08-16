#!/usr/bin/env bash
set -euo pipefail

apt-get install -y espeak-ng libsndfile1 ffmpeg
/opt/venv/bin/pip install --no-cache-dir \
  'diffusers==0.39.0' \
  'accelerate>=1.10,<2' \
  'kokoro==0.9.4' \
  'spacy>=3.7,<3.8' \
  'soundfile>=0.13,<1' \
  'httpx>=0.27,<1'

curl -fL --retry 3 --connect-timeout 20 --max-time 300 \
  'https://huggingface.co/spacy/en_core_web_sm/resolve/main/en_core_web_sm-any-py3-none-any.whl' \
  -o /tmp/en_core_web_sm-3.8.0-py3-none-any.whl
/opt/venv/bin/pip install --no-cache-dir --no-deps \
  /tmp/en_core_web_sm-3.8.0-py3-none-any.whl

# The base image includes a CUDA-only flash_attn package whose top-level import
# breaks vLLM rotary embeddings on ROCm. Qwen3 uses the ROCm/Triton fallback.
/opt/venv/bin/pip uninstall -y flash-attn || true
