# =============================================================================
# AMD Radeon / ROCm image for quadruped/humanoid locomotion RL (MJX-JAX).
# =============================================================================
# The base image already ships a ROCm-enabled JAX build, which is the hard part
# to get right on AMD. Pick the tag that matches the ROCm version on your
# Radeon instance (see README "Choosing the base image tag").
#
#   Browse tags: https://hub.docker.com/r/rocm/jax-community/tags
#
# Build (override the tag to match your instance's ROCm):
#   docker build --build-arg BASE_TAG=<tag> -t amd-locomotion .
#
# Run (must pass the GPU devices through):
#   docker run -it --rm \
#     --device=/dev/kfd --device=/dev/dri \
#     --group-add video --security-opt seccomp=unconfined \
#     -v "$PWD/outputs:/app/outputs" \
#     amd-locomotion bash scripts/00_verify_rocm.sh
# =============================================================================
ARG BASE_TAG=latest
FROM rocm/jax-community:${BASE_TAG}

# osmesa lets MuJoCo render without a display (headless cloud instance).
ENV MUJOCO_GL=osmesa \
    XLA_FLAGS="--xla_gpu_enable_command_buffer=" \
    PYTHONUNBUFFERED=1

# System deps for headless OpenGL software rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libosmesa6-dev libgl1-mesa-glx libglfw3 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install framework deps WITHOUT touching the base image's ROCm JAX build.
# (requirements.txt intentionally does not pin jax.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sanity: fail the build early if JAX cannot see the ROCm backend at import.
# (Device visibility itself is only testable at `docker run` with GPUs passed in.)
RUN python3 -c "import jax, mujoco; from mujoco import mjx; import mujoco_playground; print('imports OK, jax', jax.__version__)"

CMD ["bash", "scripts/00_verify_rocm.sh"]
