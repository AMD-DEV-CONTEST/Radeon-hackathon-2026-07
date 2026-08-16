#!/usr/bin/env bash
set -euo pipefail

ROOT=/persistent/silent-core
SOURCE="$ROOT/tools/llama.cpp"
BUILD="$SOURCE/build-rocm"
MODEL_DIR="$ROOT/models/Qwen3-8B-GGUF"
export HF_HOME="$ROOT/cache/huggingface"
export HF_HUB_DISABLE_XET=1

mkdir -p "$ROOT/tools" "$MODEL_DIR" "$ROOT/run" "$ROOT/logs"
if [[ ! -d "$SOURCE/.git" ]]; then
  git -c http.sslVerify=false clone --depth 1 \
    https://github.com/ggml-org/llama.cpp.git "$SOURCE"
fi

cmake -S "$SOURCE" -B "$BUILD" \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1100 \
  -DLLAMA_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --parallel 8 --target llama-server llama-bench

/opt/venv/bin/huggingface-cli download Qwen/Qwen3-8B-GGUF \
  Qwen3-8B-Q4_K_M.gguf \
  --local-dir "$MODEL_DIR"
test -x "$BUILD/bin/llama-server"
test -f "$MODEL_DIR/Qwen3-8B-Q4_K_M.gguf"
touch "$ROOT/run/llamacpp-prepare.done"
