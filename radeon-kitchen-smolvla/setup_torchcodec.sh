#!/bin/bash
# Build torchcodec 0.10.0 from source (CPU-only) for ROCm.
#
# Why CPU-only: torchcodec's GPU decode path uses NVIDIA NVDEC (CUDA).
# AMD GPUs have VCN hardware but torchcodec has no VA-API backend yet,
# so CPU libavcodec is the only working path on ROCm.
# This is fine for training — video I/O is not the bottleneck.
set -e

TORCHCODEC_VERSION="v0.10.0"
BUILD_DIR="/tmp/torchcodec"

# FFmpeg dev headers are required for cmake pkg-config discovery
echo "[torchcodec] Installing build prerequisites ..."
apt-get update -qq 2>/dev/null
apt-get install -y -qq pkg-config \
    libavdevice-dev libavfilter-dev libavformat-dev \
    libavcodec-dev libavutil-dev libswresample-dev libswscale-dev \
    > /dev/null 2>&1
pip install -q pybind11

echo "[torchcodec] Cloning ${TORCHCODEC_VERSION} ..."
rm -rf "${BUILD_DIR}"
git clone --depth 1 --branch "${TORCHCODEC_VERSION}" \
    https://github.com/pytorch/torchcodec.git "${BUILD_DIR}"

TORCH_CMAKE="$(python -c 'import torch; print(torch.utils.cmake_prefix_path)')/Torch"
PYBIND11_CMAKE="$(python -c 'import pybind11; print(pybind11.get_cmake_dir())')"
SITE_PKG="$(python -c 'import site; print(site.getsitepackages()[0])')"

echo "[torchcodec] Configuring (CPU-only, ENABLE_CUDA=OFF) ..."
mkdir -p "${BUILD_DIR}/build" && cd "${BUILD_DIR}/build"
cmake "${BUILD_DIR}" \
    -DENABLE_CUDA=OFF \
    -DTorch_DIR="${TORCH_CMAKE}" \
    -Dpybind11_DIR="${PYBIND11_CMAKE}" \
    -DTORCHCODEC_DISABLE_COMPILE_WARNING_AS_ERROR=ON \
    -DCMAKE_BUILD_TYPE=Release

echo "[torchcodec] Building ($(nproc) jobs) ..."
cmake --build . -j"$(nproc)"

echo "[torchcodec] Copying built libraries to site-packages ..."
find "${BUILD_DIR}/build" -name 'libtorchcodec_*.so' -exec cp -v {} "${SITE_PKG}/torchcodec/" \;

echo "[torchcodec] Verifying ..."
python -c "import torchcodec; print('torchcodec OK:', torchcodec.__version__)"
echo "[torchcodec] Done."
