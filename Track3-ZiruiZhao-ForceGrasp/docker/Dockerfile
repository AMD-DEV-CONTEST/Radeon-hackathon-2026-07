ARG BASE_IMAGE=rocm/pytorch:rocm7.2_ubuntu24.04_py3.12_pytorch_release_2.9.1
FROM ${BASE_IMAGE}

LABEL description="Pre-built workshop image for Robot Synthetic Data Generation (CDNA3 / RDNA4)"
LABEL maintainer="AMD AIM"

ENV PYOPENGL_PLATFORM=egl
ENV DEBIAN_FRONTEND=noninteractive
# Pin Taichi kernel cache to a fixed path so it survives bind-mount overlays
ENV TI_OFFLINE_CACHE_FILE_PATH=/opt/taichi_cache

# ── System packages ──────────────────────────────────────────────────────
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        xvfb ffmpeg git pkg-config \
        libavdevice-dev libavfilter-dev libavformat-dev \
        libavcodec-dev libavutil-dev libswresample-dev libswscale-dev && \
    rm -rf /var/lib/apt/lists/*

# ── Python packages ──────────────────────────────────────────────────────
RUN pip install --no-cache-dir -q \
    git+https://github.com/Genesis-Embodied-AI/Genesis.git@main \
    lerobot==0.4.4 transformers accelerate safetensors \
    matplotlib Pillow jupyter ipykernel num2words pybind11 \
    "rerun-sdk[notebook]" && \
    pip install --no-cache-dir --force-reinstall -q \
        "scikit-image>=0.22" "numpy==2.1.2"

# ── torchcodec CPU-only build ────────────────────────────────────────────
ARG TORCHCODEC_VERSION=v0.10.0
RUN export PYTORCH_ROCM_ARCH="gfx942" && \
    git clone --depth 1 --branch ${TORCHCODEC_VERSION} \
        https://github.com/pytorch/torchcodec.git /tmp/torchcodec && \
    TORCH_CMAKE="$(python -c 'import torch; print(torch.utils.cmake_prefix_path)')/Torch" && \
    PYBIND11_CMAKE="$(python -c 'import pybind11; print(pybind11.get_cmake_dir())')" && \
    SITE_PKG="$(python -c 'import site; print(site.getsitepackages()[0])')" && \
    mkdir -p /tmp/torchcodec/build && cd /tmp/torchcodec/build && \
    cmake /tmp/torchcodec \
        -DENABLE_CUDA=OFF \
        -DTorch_DIR="${TORCH_CMAKE}" \
        -Dpybind11_DIR="${PYBIND11_CMAKE}" \
        -DTORCHCODEC_DISABLE_COMPILE_WARNING_AS_ERROR=ON \
        -DCMAKE_BUILD_TYPE=Release && \
    cmake --build . -j"$(nproc)" && \
    find /tmp/torchcodec/build -name 'libtorchcodec_*.so' -exec cp -v {} "${SITE_PKG}/torchcodec/" \; && \
    rm -rf /tmp/torchcodec

# ── Workshop repo (baked in for cache warmup, students mount over it) ────
COPY . /opt/workshop
WORKDIR /opt/workshop

# ── Download kitchen GLB assets (~130 MB) ────────────────────────────────
RUN python scripts/00_download_kitchen.py

# ── Pre-download SmolVLA base model + HF dataset ─────────────────────────
RUN python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('lerobot/smolvla_base'); \
snapshot_download('lidavidsh/franka-pick-kitchen-up-wrist-100ep-genesis', repo_type='dataset')"

# ── Warm up Taichi CPU kernel cache (the 20-30 min compile) ──────────────
RUN xvfb-run -a python docker/warmup_cache.py

# ── Pre-create local demo datasets (prevents race conditions in workshop) ─
RUN xvfb-run -a python scripts/01_gen_data.py \
        --n-episodes 2 \
        --repo-id local/workshop-flat-demo \
        --seed 42 \
        --no-videos && \
    xvfb-run -a python scripts/02_gen_data_custom_scene.py \
        --scene rustic_kitchen \
        --anchor floor_origin \
        --camera-layout up_wrist \
        --n-episodes 2 \
        --repo-id local/workshop-kitchen-wrist-demo \
        --seed 42 \
        --no-videos \
        --task 'Pick up the red cube.'

# ── Students bind-mount their repo to /workspace/workshop ────────────────
WORKDIR /workspace/workshop
CMD ["bash"]
