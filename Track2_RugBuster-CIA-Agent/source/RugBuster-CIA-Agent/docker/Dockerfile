# RugBuster CIA Intelligence Agent — AMD AI DevMaster Hackathon (Track 2)
#
# Best-effort ROCm container. ROCm-in-Docker on Windows dev boxes (Z13,
# gfx1151) is not practical — WSL2 GPU passthrough for ROCm is still rough
# for this target, so this image is intended to be BUILT AND RUN on the
# Linux-based AMD Radeon Cloud instance at submission time, not on the
# Windows dev box. On the Windows/Z13 dev box, use the native install
# path documented in README.md ("Local dev on Windows / Z13") instead —
# do not fight WSL2+ROCm+Docker on the dev box just to run this file.
#
# No gfx-target is hardcoded here (see src/gpu_config.py) — ROCM_GFX_TARGET
# can be passed at `docker run` time to pin one if auto-detection via
# rocminfo doesn't find the right device inside the container.

FROM rocm/dev-ubuntu-22.04:6.1

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    CIA_LLM_MODEL_DIR=/app/models

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv git cmake build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Everything except llama-cpp-python installs the normal way.
RUN pip3 install --upgrade pip \
    && pip3 install -r requirements.txt

# Rebuild llama-cpp-python against ROCm/HIPBLAS explicitly, so GPU offload
# actually uses the Radeon GPU instead of falling back to CPU-only wheels.
RUN CMAKE_ARGS="-DGGML_HIPBLAS=on" pip3 install --force-reinstall --no-cache-dir llama-cpp-python

COPY src/ ./src/
COPY main.py .

# Model is not baked into the image (multi-GB GGUF) — mount it or let
# llm_client.py download it from ffurduj/syndicate-gguf on first run.
VOLUME ["/app/models"]

ENTRYPOINT ["python3", "main.py"]
CMD ["--help"]
