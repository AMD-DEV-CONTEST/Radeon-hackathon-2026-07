# Chaal on ROCm.
#
# The apt line is the part that is easy to get wrong. A ROCm image has no
# OpenGL libraries, because nothing in the compute stack needs them, but
# Genesis builds an offscreen renderer during scene.build() whether or not
# anything is being rendered. Without libEGL every run dies with a PyOpenGL
# AttributeError that says nothing about the cause. See docs/upstream.md.
FROM rocm/pytorch:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYOPENGL_PLATFORM=egl

RUN apt-get update && apt-get install -y --no-install-recommends \
        libegl1 \
        libegl-mesa0 \
        libgl1-mesa-dri \
        libosmesa6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/chaal
COPY pyproject.toml README.md ./
COPY chaal ./chaal
COPY scripts ./scripts

# genesis-world does not declare torch, on purpose: it expects you to bring the
# build that matches your accelerator. The base image already has the ROCm one,
# so it must not be replaced here.
RUN pip install --no-cache-dir -e . \
    && python -c "import torch; assert 'rocm' in torch.__version__, torch.__version__"

# Fails loudly if the GPU or the GL platform is missing, rather than at the
# first scene build several minutes into a training run.
HEALTHCHECK --interval=60s --timeout=30s CMD chaal doctor || exit 1

ENTRYPOINT ["chaal"]
CMD ["doctor"]
