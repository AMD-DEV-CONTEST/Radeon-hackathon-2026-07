#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 OPENSPLAT_SOURCE_DIR" >&2
  exit 2
fi

source_dir=$1
rocm_venv=${ROCM_VENV:-/root/opensplat-env}
build_dir=${OPENSPLAT_BUILD_DIR:-$source_dir/build}
include_overlay=${ROCM_INCLUDE_OVERLAY:-/root/rocm-include-overlay}
parallel_jobs=${BUILD_JOBS:-8}
expected_commit=9fb62fde8b7b8c416121d3cbdcda278ffd9682f7
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for executable in cmake ninja git; do
  if ! command -v "$executable" >/dev/null; then
    echo "missing build dependency: $executable" >&2
    exit 1
  fi
done
if [[ ! -x "$rocm_venv/bin/rocm-sdk" ]]; then
  echo "TheRock ROCm development environment is missing: $rocm_venv" >&2
  exit 1
fi
if [[ $(git -C "$source_dir" rev-parse HEAD) != "$expected_commit" ]]; then
  echo "OpenSplat must be pinned to $expected_commit" >&2
  exit 1
fi

apply_patch_once() {
  local patch_file=$1
  if git -C "$source_dir" apply --check "$patch_file" 2>/dev/null; then
    git -C "$source_dir" apply "$patch_file"
  elif ! git -C "$source_dir" apply --reverse --check "$patch_file" 2>/dev/null; then
    echo "patch does not apply cleanly: $patch_file" >&2
    exit 1
  fi
}

apply_patch_once "$script_dir/../patches/opensplat-rocm-home.patch"
apply_patch_once "$script_dir/../patches/opensplat-force-rocm-include.patch"

rocm_root=$("$rocm_venv/bin/rocm-sdk" path --root)
torch_prefix=$(
  "$rocm_venv/bin/python" -c \
    'import torch; print(torch.utils.cmake_prefix_path)'
)

mkdir -p "$include_overlay"
ln -sfn "$rocm_root/include/hip" "$include_overlay/hip"

export PATH="$rocm_venv/bin:$PATH"
export HIP_PATH="$rocm_root"
export ROCM_HOME="$rocm_root"
export PYTORCH_ROCM_ARCH=gfx1100

cmake -S "$source_dir" -B "$build_dir" -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DGPU_RUNTIME=HIP \
  -DHIP_PATH="$rocm_root" \
  -DROCM_ROOT="$rocm_root" \
  -DCMAKE_HIP_COMPILER="$rocm_root/llvm/bin/clang++" \
  -DCMAKE_HIP_ARCHITECTURES=gfx1100 \
  -DCMAKE_HIP_FLAGS="-I$include_overlay" \
  -DCMAKE_PREFIX_PATH="$torch_prefix;$rocm_root" \
  -DOPENSPLAT_BUILD_SIMPLE_TRAINER=ON \
  -DOPENSPLAT_USE_FAST_MATH=OFF

cmake --build "$build_dir" --parallel "$parallel_jobs"
"$build_dir/opensplat" --version
