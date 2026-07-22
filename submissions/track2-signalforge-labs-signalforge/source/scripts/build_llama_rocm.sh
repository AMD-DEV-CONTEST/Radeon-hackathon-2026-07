#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${LLAMA_CPP_DIR:-$repo_root/runtime/llama.cpp}"
revision="305ba519ab61cdff8044922cba2347826a04453f"
upstream="${LLAMA_CPP_REPOSITORY:-https://github.com/ggml-org/llama.cpp.git}"
platform_proxy="https://gh-proxy.org/https://github.com/ggml-org/llama.cpp.git"

if [[ ! -d "$runtime_dir/.git" ]]; then
  if ! git clone "$upstream" "$runtime_dir"; then
    rm -rf "$runtime_dir"
    git clone "$platform_proxy" "$runtime_dir"
  fi
fi

if ! git -C "$runtime_dir" fetch --depth 1 origin "$revision"; then
  git -C "$runtime_dir" fetch --depth 1 "$platform_proxy" "$revision"
fi
git -C "$runtime_dir" checkout --detach "$revision"

cmake \
  -S "$runtime_dir" \
  -B "$runtime_dir/build-rocm" \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS=gfx1100 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$runtime_dir/build-rocm" --target llama-server llama-cli -j"${BUILD_JOBS:-8}"

git -C "$runtime_dir" rev-parse HEAD
