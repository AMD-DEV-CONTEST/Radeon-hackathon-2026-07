# syntax=docker/dockerfile:1.7
# Self-contained RadeonVLA-Reflex image for one AMD Radeon GPU.
# Build: docker build --pull -f docker/Dockerfile -t radeonvla-reflex:rocm7.2.1 .

ARG BASE_IMAGE=docker.io/rocm/dev-ubuntu-24.04:7.2.1-complete@sha256:3db551c4e1229aac1857ac44fcb6141bb749f41348eb572452f11279153c13c3
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="RadeonVLA-Reflex" \
      org.opencontainers.image.description="Interruptible and recoverable SmolVLA control on AMD Radeon" \
      org.opencontainers.image.source="https://github.com/zzw-rgb/Radeon-hackathon-2026-07" \
      org.opencontainers.image.version="0.1.0"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Keep the default build portable while allowing a reachable package mirror on
# restricted networks:
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
#     --build-arg PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn ...
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git ffmpeg \
        libdrm2 libgbm1 libgl1 libglu1-mesa libegl1 libgles2 libglvnd0 libosmesa6 \
        libglib2.0-0 libsm6 libxext6 libxrender1 libx11-6 libxi6 libxrandr2 \
        libxcursor1 libxinerama1 libxfixes3 libvulkan1 mesa-vulkan-drivers \
        python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -f render && groupadd -f video && usermod -aG render,video root

WORKDIR /workspace/radeonvla-reflex

# Keep an isolated Python environment while retaining optional HIP packages from the base.
RUN python3 -m venv --system-site-packages /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

ARG TORCH_WHL=torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
ARG VISION_WHL=torchvision-0.24.0+rocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl
ARG AUDIO_WHL=torchaudio-2.9.0+rocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl
ARG TRITON_WHL=triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl
ARG ROCM_WHL_BASE=https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1

# Install dependencies before the full source copy so code-only edits keep this layer cached.
COPY requirements.remote.txt pyproject.toml README.md ./
COPY src ./src

RUN set -eux; \
    if ! python -c "import torch; assert torch.__version__.startswith('2.9.1'); assert str(torch.version.hip).startswith('7.2')"; then \
      mkdir -p /tmp/rocm-wheels; \
      for wheel in "$TORCH_WHL" "$VISION_WHL" "$AUDIO_WHL" "$TRITON_WHL"; do \
        encoded="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$wheel")"; \
        wget --https-only --tries=3 -O "/tmp/rocm-wheels/$wheel" "${ROCM_WHL_BASE}/${encoded}"; \
      done; \
      pip uninstall -y torch torchvision torchaudio triton || true; \
      pip install --no-cache-dir \
        "/tmp/rocm-wheels/$TORCH_WHL" \
        "/tmp/rocm-wheels/$VISION_WHL" \
        "/tmp/rocm-wheels/$AUDIO_WHL" \
        "/tmp/rocm-wheels/$TRITON_WHL"; \
      rm -rf /tmp/rocm-wheels; \
    fi; \
    pip install --no-cache-dir -r requirements.remote.txt; \
    pip install --no-cache-dir -e .; \
    pip check

# The image now contains the complete runnable project. Datasets/checkpoints remain external volumes.
COPY . .
RUN chmod +x docker/entrypoint.sh scripts/*.sh \
    && python -m radeonvla.submission_audit \
    && python -m pytest \
    && python -m ruff check src tests

ENV PYOPENGL_PLATFORM=egl \
    EGL_DEVICE_ID=0 \
    HSA_ENABLE_SDMA=0 \
    HIP_VISIBLE_DEVICES=0 \
    BACKEND=amdgpu

RUN python -c "import torch; assert torch.__version__.startswith('2.9.1'); assert str(torch.version.hip).startswith('7.2'); print(torch.__version__, torch.version.hip)" \
    && python -c "import genesis, lerobot; print('genesis/lerobot imports ok')"

RUN mkdir -p datasets checkpoints outputs artifacts /root/.cache/huggingface
VOLUME ["/workspace/radeonvla-reflex/datasets", "/workspace/radeonvla-reflex/checkpoints", "/workspace/radeonvla-reflex/outputs", "/workspace/radeonvla-reflex/artifacts", "/root/.cache/huggingface"]

ENTRYPOINT ["/workspace/radeonvla-reflex/docker/entrypoint.sh"]
CMD ["help"]
