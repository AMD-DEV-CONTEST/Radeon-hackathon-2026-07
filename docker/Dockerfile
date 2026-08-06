# syntax=docker/dockerfile:1
# =============================================================================
# ChromaSort-VLA — YCB Color Sorting (SmolVLA + Qwen3-VL on AMD ROCm)
#
# Build image for the full pipeline:
#   physics (Genesis) + policy learning (LeRobot/SmolVLA) + VLM (Qwen3-VL-8B)
#
# Base: official AMD ROCm dev image for Ubuntu 24.04 (PyTorch-ROCm compatible).
# Requires a Docker host with the AMD GPU exposed via /dev/kfd + /dev/dri.
# =============================================================================
FROM rocm/dev-ubuntu-24.04:7.2.1

LABEL org.opencontainers.image.title="ChromaSort-VLA YCB Color Sorting"
LABEL org.opencontainers.image.description="Dual-VLM (Qwen3-VL + SmolVLA) YCB object color sorting on AMD Radeon GPU"
LABEL org.opencontainers.image.vendor="AMD Radeon Hackathon 2026 Track 3"

# -----------------------------------------------------------------------------
# System packages (ROCm base already has the ROCm stack + PyTorch wheels)
# -----------------------------------------------------------------------------
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=0 \
    TRANSFORMERS_OFFLINE=0

# ROCm/PyTorch wheels from the official AMD repo (installed by base image).
# Extra system deps needed by Genesis + OpenGL rendering + video encoding.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
        wget \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        ocl-icd-libopencl1 \
        libsndfile1 \
        libegl1 \
        libxext6 \
        libxrender1 \
        libxrandr2 \
        libxinerama1 \
        libxcursor1 \
        libxi6 \
        libsm6 \
        libice6 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# Python: install core deps. Genesis is a git install (pinned commit).
# -----------------------------------------------------------------------------
WORKDIR /opt/robopilot

# Copy the pinned dependency manifest first for Docker layer caching.
COPY requirements.txt /opt/robopilot/requirements.txt

RUN pip install --upgrade pip wheel setuptools && \
    pip install -r /opt/robopilot/requirements.txt

# -----------------------------------------------------------------------------
# Project source
# -----------------------------------------------------------------------------
COPY color_sort/ /opt/robopilot/color_sort/
COPY assets/ /opt/robopilot/assets/
COPY README.md /opt/robopilot/README.md

# Model weight directories (populated at runtime by download_models.py)
ENV HF_HOME=/opt/models \
    SMOLVLA_BASE=/opt/models/smolvla_base \
    QWEN3VL_PATH=/opt/models/modelscope/models/Qwen--Qwen3-VL-8B-Instruct/snapshots/master

# -----------------------------------------------------------------------------
# Entrypoint: download weights (if missing) then hand off to the given command.
# -----------------------------------------------------------------------------
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /opt/robopilot/color_sort
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
