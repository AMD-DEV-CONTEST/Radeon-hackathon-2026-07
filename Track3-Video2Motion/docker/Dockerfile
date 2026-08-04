# syntax=docker/dockerfile:1.7
# ============================================================================
# Video2Motion — human video to Unitree G1 control policy, on AMD ROCm
#
# Three Python environments live in this image and MUST stay separate:
#   /opt/venv/gvhmr   PyTorch-ROCm + pytorch3d   (no jax)
#   /opt/venv/gmr     retargeting deps
#   /opt/venv/mjx     JAX-ROCm + MuJoCo + brax   (no torch)
# Installing them together breaks both sides, so the backend shells out to
# each one and the stages exchange data through files.
#
# Build (needs a real Docker daemon with CAP_SYS_ADMIN — a non-privileged
# container cannot build this, `docker build` fails with
# "unshare: operation not permitted"):
#
#   DOCKER_BUILDKIT=1 docker build -t video2motion:1.0 -f docker/Dockerfile .
#
# Run:
#   docker run --rm -it \
#     --device=/dev/kfd --device=/dev/dri --group-add video \
#     --ipc=host --shm-size 16G \
#     -p 7860:7860 \
#     -v $PWD/smpl_models:/opt/models/body_models:ro \
#     -v $PWD/workdir:/workspace \
#     video2motion:1.0
#
# ⚠️ SMPL / SMPL-X are registration-gated and their licence forbids
#    redistribution, so they are NOT baked in. Download them yourself and
#    mount them at /opt/models/body_models (see docker/README.md).
# ============================================================================

FROM rocm/dev-ubuntu-22.04:7.2.1-complete AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev python3-pip \
        git wget curl ca-certificates build-essential cmake ninja-build \
        ffmpeg xvfb libegl1 libgl1 libglfw3 libosmesa6 \
        libeigen3-dev libyaml-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 1. mjx — JAX-ROCm, MuJoCo, MJX, brax, the web app
# ---------------------------------------------------------------------------
FROM base AS venv-mjx
RUN python3.12 -m venv /opt/venv/mjx
ENV PATH=/opt/venv/mjx/bin:$PATH

# JAX-ROCm first, then verify. If this prints "cpu", nothing downstream works.
RUN pip install --upgrade pip \
 && pip install --upgrade "jax[rocm7-local]" \
 && python -c "import jax; print('jax backend:', jax.default_backend())"

RUN pip install \
        "mujoco>=3.11" "mujoco-mjx>=3.11" brax mujoco_playground \
        gradio matplotlib imageio \
        "setuptools<81"          # >=81 dropped pkg_resources; lightning breaks

# ---------------------------------------------------------------------------
# 2. gvhmr — PyTorch-ROCm + pytorch3d
# ---------------------------------------------------------------------------
FROM base AS venv-gvhmr
RUN python3.12 -m venv /opt/venv/gvhmr
ENV PATH=/opt/venv/gvhmr/bin:$PATH
RUN pip install --upgrade pip "setuptools<81"

# The ROCm torch wheels pin a matching local triton build, so all four must be
# installed in one transaction or pip cannot resolve triton==*+rocm*.
ARG TORCH_INDEX=https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/
RUN pip install --index-url ${TORCH_INDEX} \
        torch torchvision torchaudio pytorch-triton-rocm

RUN pip install \
        hydra-core omegaconf einops timm opencv-python-headless \
        yacs joblib chumpy-fix imageio imageio-ffmpeg \
        "numpy<2" pycolmap wis3d "ultralytics>=8.4"
#   ultralytics 8.2.42 + torch>=2.6: weights_only=True blocks the YOLO load
#   wis3d / pycolmap are NOT optional — cv2_utils.py imports them at module level

# pytorch3d must be built from source, and MAX_JOBS is mandatory: an unbounded
# build spawns 30+ cc1plus processes and can take the machine down.
ENV MAX_JOBS=8 FORCE_CUDA=0
RUN git clone --depth 1 https://github.com/facebookresearch/pytorch3d /tmp/p3d \
 && pip install --no-build-isolation /tmp/p3d \
 && rm -rf /tmp/p3d

# ---------------------------------------------------------------------------
# 3. gmr — retargeting
# ---------------------------------------------------------------------------
FROM base AS venv-gmr
RUN python3.12 -m venv /opt/venv/gmr
ENV PATH=/opt/venv/gmr/bin:$PATH
RUN pip install --upgrade pip "setuptools<81" \
 && pip install "mujoco>=3.11" "numpy<2" scipy pyyaml rich \
        smplx trimesh opencv-python-headless

# ---------------------------------------------------------------------------
# 4. CycloneDDS + unitree_sdk2_python  (layer-3 DDS transport)
# ---------------------------------------------------------------------------
FROM base AS dds
RUN git clone --depth 1 -b releases/0.10.x \
        https://github.com/eclipse-cyclonedds/cyclonedds /tmp/cdds \
 && cmake -S /tmp/cdds -B /tmp/cdds/build -DCMAKE_INSTALL_PREFIX=/opt/cyclonedds \
        -DBUILD_EXAMPLES=OFF \
 && cmake --build /tmp/cdds/build --target install -j"$(nproc)" \
 && rm -rf /tmp/cdds

# ---------------------------------------------------------------------------
# Final image
# ---------------------------------------------------------------------------
FROM base

COPY --from=venv-mjx   /opt/venv/mjx   /opt/venv/mjx
COPY --from=venv-gvhmr /opt/venv/gvhmr /opt/venv/gvhmr
COPY --from=venv-gmr   /opt/venv/gmr   /opt/venv/gmr
COPY --from=dds        /opt/cyclonedds /opt/cyclonedds

ENV CYCLONEDDS_HOME=/opt/cyclonedds \
    LD_LIBRARY_PATH=/opt/cyclonedds/lib:${LD_LIBRARY_PATH}

# unitree_sdk2_python + unitree_mujoco.
# pygame is imported unconditionally by the bridge even with the joystick off.
RUN /opt/venv/mjx/bin/pip install pygame \
 && git clone --depth 1 https://github.com/unitreerobotics/unitree_sdk2_python \
        /opt/unitree_sdk2_python \
 && /opt/venv/mjx/bin/pip install -e /opt/unitree_sdk2_python --no-deps \
 && /opt/venv/mjx/bin/pip install cyclonedds==0.10.2 \
 && git clone --depth 1 https://github.com/unitreerobotics/unitree_mujoco \
        /opt/unitree_mujoco

# Upstream repos. GVHMR pins its own submodules.
RUN git clone --depth 1 https://github.com/zju3dv/GVHMR /opt/GVHMR \
 && git clone --depth 1 https://github.com/YanjieZe/GMR /opt/GMR

# ---- our code ----
WORKDIR /opt/video2motion
COPY code/            /opt/video2motion/
COPY deploy/          /opt/video2motion/deploy/
COPY docker/entrypoint.sh /opt/entrypoint.sh

# ---- third-party patches (see 踩坑清单-Docker打包必读.md) ----
#  1. PD moved out of the DDS callback — without this any stiff policy falls
#     at ~47 steps over DDS while being perfectly stable in native MuJoCo
#  2. headless recorder — the GUI build needs X11 and, under Xvfb, x11grab
#     captures a frozen frame
RUN cp /opt/video2motion/third_party_patches/unitree_sdk2py_bridge.py \
       /opt/unitree_mujoco/simulate_python/ \
 && cp /opt/video2motion/third_party_patches/unitree_mujoco.py \
       /opt/unitree_mujoco/simulate_python/ \
 && cp /opt/video2motion/third_party_patches/unitree_mujoco_headless.py \
       /opt/unitree_mujoco/simulate_python/

# CycloneDDS over loopback: `lo` is not multicast-capable, so unicast must be
# configured explicitly — and on BOTH ends.
COPY docker/cyclonedds_lo.xml /opt/cyclonedds_lo.xml
ENV CYCLONEDDS_URI=file:///opt/cyclonedds_lo.xml

ENV MUJOCO_GL=egl \
    XLA_PYTHON_CLIENT_PREALLOCATE=false \
    MPLBACKEND=Agg \
    V2M_WORKDIR=/workspace \
    V2M_BODY_MODELS=/opt/models/body_models

RUN mkdir -p /workspace /opt/models/body_models && chmod +x /opt/entrypoint.sh
VOLUME ["/workspace", "/opt/models/body_models"]
EXPOSE 7860

ENTRYPOINT ["/opt/entrypoint.sh"]
CMD ["web"]
