# Reproducible ROCm environment for the SO-101 sim-to-real pipeline.
#
# Base image is AMD's ROCm PyTorch build — the same torch 2.9.1+rocm7.2.1.gitff65f5bc the submitted
# results were produced with. Do not swap in a pip-installed torch: the wheel on PyPI is
# the CUDA build and will not see the Radeon GPU.
FROM rocm/pytorch:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HSA_OVERRIDE_GFX_VERSION="" \
    # LeRobot resolves video decoding through torchcodec by default; that extension is
    # ABI-incompatible with AMD's custom torch build (see docs/Technical_Report.md).
    # Every training/eval command in this submission passes --dataset.video_backend=pyav.
    LEROBOT_VIDEO_BACKEND=pyav \
    # Genesis rasterises the two cameras offscreen through pyrender. Its default pyglet
    # path needs a display and dies headless with "IndexError: list index out of range"
    # from display.get_default_screen(). EGL renders without one, so data collection and
    # sim evaluation work in a container. Fall back to osmesa (software) if the GPU's
    # EGL stack is unavailable.
    PYOPENGL_PLATFORM=egl

# Genesis renders offscreen through OpenGL; ffmpeg is needed for dataset video encode/decode.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 libosmesa6 libegl1 git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY submission/requirements.txt /workspace/requirements.txt
# --no-deps on torch-adjacent packages is unnecessary here because the base image already
# satisfies torch; pip will keep it. torchcodec is deliberately never installed.
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY submission/ /workspace/

# Genesis compiles its kernels on first use; warm the cache so the first training step of a
# fresh container is not paying a multi-minute JIT penalty.
RUN python -c "import genesis" || true

CMD ["/bin/bash"]
