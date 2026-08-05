ARG BASE_IMAGE=rocm/pytorch:rocm7.2.1_ubuntu24.04_py3.12_pytorch_release_2.9.1
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    XDG_RUNTIME_DIR=/tmp/runtime-physicalai \
    SDL_AUDIODRIVER=dummy

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p ${XDG_RUNTIME_DIR} \
    && chmod 700 ${XDG_RUNTIME_DIR}

WORKDIR /workspace/PhysicalAI-ROCm

COPY requirements-lock.txt ./requirements-lock.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements-lock.txt

COPY . .

CMD ["/bin/bash"]
