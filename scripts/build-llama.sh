#!/usr/bin/env bash
# build-llama.sh — Compile llama.cpp with ROCm/HIPBLAS on AMD Cloud
#
# Usage: bash scripts/build-llama.sh
# Output: /opt/llama.cpp/llama-server binary
# Prerequisite: ROCm installed (AMD Cloud default)
set -euo pipefail
LLAMA_DIR=/opt/llama.cpp
LLAMA_REPO=https://github.com/ggml-org/llama.cpp
LLAMA_COMMIT=035cd8f9a  # Matches design doc (build 9766)

echo "===== [1/4] Checking ROCm ====="
if ! command -v rocminfo >/dev/null 2>&1; then
  echo "  [ERROR] rocminfo not found, ROCm not installed?"
  echo "  AMD Cloud should have ROCm pre-installed, check environment"
  exit 1
fi
GPU_INFO=$(rocminfo 2>/dev/null | grep "Marketing Name" | head -1 || true)
echo "  GPU: ${GPU_INFO:-unknown}"
echo "  ROCm: OK"

echo "===== [2/4] Cloning llama.cpp ====="
if [ -d "$LLAMA_DIR/.git" ]; then
  echo "  Already exists, pulling updates..."
  cd "$LLAMA_DIR"
  git fetch --all -q
  git checkout "$LLAMA_COMMIT" -q 2>/dev/null || echo "  (commit not found, using latest)"
else
  git clone --recursive "$LLAMA_REPO" "$LLAMA_DIR"
  cd "$LLAMA_DIR"
  git checkout "$LLAMA_COMMIT" -q 2>/dev/null || echo "  (commit not found, using latest)"
fi

echo "===== [3/4] Compiling (ROCm/HIPBLAS) ====="
# AMD Cloud W7900D = gfx1100, officially supported by ROCm, no override needed
cmake -B build \
  -DGGML_HIPBLAS=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_CUDA_NO_PEER_MEMORY=ON \
  2>&1 | tail -5

cmake --build build --config Release -j"$(nproc)" \
  --target llama-server llama-bench \
  2>&1 | tail -5

echo "===== [4/4] Install ====="
# Symlink: /opt/llama.cpp/llama-server -> build/bin/llama-server
# Unified path, both bootstrap.sh and setup-cloud.sh use /opt/llama.cpp/llama-server
mkdir -p /opt/llama.cpp/build/bin
ln -sf build/bin/llama-server /opt/llama.cpp/llama-server
ln -sf build/bin/llama-bench /opt/llama.cpp/llama-bench
echo "  llama-server: $(ls -la /opt/llama.cpp/llama-server 2>/dev/null || echo 'FAIL')"
echo "  ldd verifying ROCm libs:"
ldd /opt/llama.cpp/llama-server 2>/dev/null | grep -E 'amdhip64|hipblas|rocblas' || echo "  [WARN] ROCm libs not detected"
echo "===== done ====="
