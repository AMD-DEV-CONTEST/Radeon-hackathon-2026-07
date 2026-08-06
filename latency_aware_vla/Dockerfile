# Preferable Docker packaging for Track 3 (ROCm).
# This is a reproducible *recipe*, not a pre-baked image with 10GB+ weights.
# Build on a machine with AMD ROCm / or use the contest Radeon Cloud venv instead.
#
#   docker build -t latency-aware-vla:track3 .
#   docker run --device=/dev/kfd --device=/dev/dri --group-add video \
#     -v /path/to/models:/models -v /path/to/datasets:/data \
#     -it latency-aware-vla:track3 bash
#
# Official scores in this submission were produced on Radeon Cloud with
# /workspace/rdna (see ENVIRONMENT.md). Use that path if Docker ROCm
# device passthrough is unavailable.

FROM rocm/pytorch:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

WORKDIR /workspace/latency_aware_vla

# System deps commonly needed for Genesis offscreen GL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libegl1 libgl1 libglew2.2 ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-lock.txt ./
# Torch/ROCm already in base image — install the rest best-effort.
RUN pip install --no-cache-dir -r requirements-lock.txt || true

COPY . .

CMD ["bash", "-lc", "python -c \"import torch; print(torch.__version__, torch.cuda.is_available())\""]
