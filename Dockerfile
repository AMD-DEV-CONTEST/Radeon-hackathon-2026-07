# =============================================================================
# Franka Industrial Sorting VLA — AMD ROCm 7.2.1 environment (Track 3 submission)
# -----------------------------------------------------------------------------
# Reproduces the exact stack the submitted results were produced on:
#   - Ubuntu 24.04 (system Python 3.12, matching the ROCm cp312 wheels)
#   - ROCm 7.2.1 runtime
#   - Prebuilt ROCm 7.2.1 torch/vision/audio/triton wheels (repo.radeon.com)
#   - genesis-world 1.2.3 + lerobot 0.4.4 (SmolVLA) + demo deps
#   - Vulkan / OpenGL runtime so Genesis can render camera images headless
#
# Developed/verified on: AMD Radeon PRO W7900 (gfx1100, 48 GB).
#
# The image contains ONLY the Python environment (in /opt/venv). Mount the
# submission directory at runtime so code/assets stay out of the image:
#
#   docker build -f Dockerfile -t industrial-sort-vla:rocm7.2.1 .
#   docker run --rm -it --network=host \
#       --device=/dev/kfd --device=/dev/dri \
#       --group-add video --group-add render \
#       --security-opt seccomp=unconfined \
#       --cap-add=SYS_PTRACE \
#       --ipc=host --shm-size=8g \
#       -v "$PWD":/workspace/app \
#       industrial-sort-vla:rocm7.2.1
#   # then: source /opt/venv/bin/activate && cd /workspace/app
# =============================================================================
FROM rocm/dev-ubuntu-24.04:7.2.1-complete

ENV DEBIAN_FRONTEND=noninteractive

# --- System runtime deps -----------------------------------------------------
# OpenGL/Vulkan/X libs are required by Genesis' rasterizer + OpenCV image I/O;
# xvfb lets the GLX renderer run on a headless host; ffmpeg backs video export.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git \
        libgl1 libglu1-mesa libegl1 libgles2 libglvnd0 libosmesa6 \
        libglib2.0-0 libsm6 libxext6 libxrender1 libx11-6 \
        libxi6 libxrandr2 libxcursor1 libxinerama1 libxfixes3 \
        libvulkan1 vulkan-tools mesa-vulkan-drivers \
        xvfb ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Make the AMD GPU reachable for the root user inside the container.
RUN groupadd -f render && usermod -aG render,video root

# --- Python virtualenv at a fixed path (a bind-mount never shadows it) -------
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"
RUN python3.12 -m venv /opt/venv && pip install --no-cache-dir --upgrade pip

WORKDIR /workspace/app

# --- ROCm 7.2.1 torch stack ---------------------------------------------------
# Stock PyPI torch does not support ROCm; use the official AMD wheels.
ARG TORCH_WHL=torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
ARG VISION_WHL=torchvision-0.24.0+rocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl
ARG AUDIO_WHL=torchaudio-2.9.0+rocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl
ARG TRITON_WHL=triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl
ARG ROCM_WHL_BASE=https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1

RUN set -eux; \
    mkdir -p /tmp/wheels && cd /tmp/wheels; \
    for w in "$TORCH_WHL" "$VISION_WHL" "$AUDIO_WHL" "$TRITON_WHL"; do \
        url="${ROCM_WHL_BASE}/$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$w")"; \
        wget -q -O "$w" "$url"; \
    done; \
    pip install --no-cache-dir "$TORCH_WHL" "$VISION_WHL" "$AUDIO_WHL" "$TRITON_WHL"; \
    cd / && rm -rf /tmp/wheels

# --- Simulation + learning stack ----------------------------------------------
# Installed AFTER torch so the ROCm build is kept. Versions match the exact
# environment the submitted results were produced with (see README §8).
# numba/llvmlite pins: genesis-world's unpinned numba can resolve to a
# Python-3.12-incompatible stack; force compatible ones.
RUN pip install --no-cache-dir \
    "numba>=0.59" "llvmlite>=0.42" \
    genesis-world==1.2.3 \
    lerobot==0.4.4 \
    transformers==4.57.6 \
    accelerate==1.14.0 \
    datasets==4.8.5 \
    av==15.1.0 \
    torchcodec==0.10.0 \
    num2words==0.5.14 \
    wandb==0.24.2 \
    numpy==2.1.2 \
    opencv-python==5.0.0.93 \
    imageio==2.37.4 imageio-ffmpeg==0.6.0 \
    trimesh==4.12.2 \
    matplotlib==3.11.1

# --- Runtime environment ------------------------------------------------------
# Genesis renders through GLX on this stack (matches the host dev setup).
# gfx1100 is natively supported by ROCm 7.2, so no HSA_OVERRIDE is required.
ENV PYOPENGL_PLATFORM=glx \
    HSA_ENABLE_SDMA=0

# --- Build-time sanity check ---------------------------------------------------
RUN python -c "import torch, torchvision, torchaudio; \
print('torch', torch.__version__, 'hip', torch.version.hip); \
assert torch.version.hip is not None, 'torch is not a ROCm build!'" \
 && python -c "import genesis; print('genesis', genesis.__version__)" \
 && python -c "import lerobot; print('lerobot', getattr(lerobot,'__version__','ok'))"

CMD ["/bin/bash"]
