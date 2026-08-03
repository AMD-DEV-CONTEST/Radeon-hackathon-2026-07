#!/usr/bin/env bash
# Build the Paddler (https://github.com/intentee/paddler) CLI from source with CUDA support,
# tuned for Tesla P100 (Pascal, compute capability 6.0 / sm_60).
#
# Why build from source instead of using the prebuilt release binaries:
# The official prebuilt releases (paddler-bin-linux-libc*-amd64) are CPU-only. GPU inference
# requires building with `--features cuda`, which needs the CUDA toolkit + nvcc on the target
# machine.
#
# Why we pin CMAKE_CUDA_ARCHITECTURES explicitly:
# ggml-cuda's CMakeLists.txt tries to auto-detect installed GPUs ("native") and falls back to a
# generic arch list (50,61,70,75,80,86,89) if detection fails in a non-interactive/SSH build
# context. That generic list does NOT include sm_60, which P100 needs. Without pinning this, the
# resulting binary would only have PTX for compute_50 embedded, forcing a slow JIT compile at
# every startup instead of shipping native sm_60 cubins.
#
# Why RUSTFLAGS="-l nccl" is required:
# ggml's CMakeLists.txt conditionally calls `find_package(NCCL)` and links NCCL for multi-GPU
# communication if the library is present on the build host (it is, via the CUDA apt repo:
# libnccl2 / libnccl-dev). However, the llama-cpp-bindings-build crate's Rust build.rs never
# emits `cargo:rustc-link-lib=nccl` for this case (a gap in that crate, not something we control),
# so the final Rust link step fails with `undefined symbol: ncclAllReduce` unless we force the
# link manually via RUSTFLAGS.
#
# Usage: run this ON the target GPU machine (needs internet access, CUDA toolkit, rustup, and
# node >=20 installed). It clones paddler fresh into ~/paddler_build and produces
# ~/paddler_build/target/cuda/release/paddler (~650MB, includes bundled web admin panel assets).

set -euo pipefail

PADDLER_VERSION="${PADDLER_VERSION:-v4.0.0}"
BUILD_DIR="${BUILD_DIR:-$HOME/paddler_build}"
CUDA_ARCH="${CUDA_ARCH:-60-real;61-virtual}"   # 60 = P100 (Pascal datacenter), 61-virtual = fallback PTX for other Pascal GPUs (GTX 10xx / P1000 / P106 etc.)

echo "==> Building Paddler ${PADDLER_VERSION} with CUDA arch ${CUDA_ARCH}"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
git clone --depth 1 --branch "$PADDLER_VERSION" https://github.com/intentee/paddler.git "$BUILD_DIR"

cd "$BUILD_DIR"
export PATH="$HOME/.cargo/bin:/usr/local/cuda/bin:$PATH"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export CMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH"
export RUSTFLAGS="-L native=/usr/lib/x86_64-linux-gnu -l nccl"

make target/cuda/release/paddler

mkdir -p "$HOME/paddler"
cp target/cuda/release/paddler "$HOME/paddler/paddler"

echo "==> Built: $HOME/paddler/paddler"
"$HOME/paddler/paddler" --version
