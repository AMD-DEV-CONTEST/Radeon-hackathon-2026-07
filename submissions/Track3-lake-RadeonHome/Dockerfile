# RadeonHome — Language-guided, failure-aware household mobile manipulation
# AMD Radeon GPU / ROCm 7.2 / Genesis 1.3.0
#
# Build:
#   docker build -t radeonhome .
#
# Run (needs a Radeon GPU with ROCm):
#   docker run --device=/dev/kfd --device=/dev/dri --group-add video \
#     -e GENESIS_BACKEND=gs.amdgpu \
#     radeonhome radeon-home --task trash_to_trash_bin --seed 42

FROM rocm/pytorch:rocm7.2_ubuntu22.04_py3.10_pytorch_2.9.1

LABEL org.opencontainers.image.title="RadeonHome"
LABEL org.opencontainers.image.description="Failure-aware mobile manipulation on AMD Radeon/ROCm"
LABEL org.opencontainers.image.source="https://github.com/520lake/RadeonHome"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# System dependencies for Genesis rendering and EGL offscreen
RUN apt-get update && apt-get install -y --no-install-recommends \
    libegl1 libegl-mesa0 libgl1-mesa-dri libosmesa6 \
    libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Fix scikit-image / NumPy 2.x binary incompatibility on some ROCm images
RUN pip install --no-cache-dir "scikit-image>=0.25" "imageio[ffmpeg]>=2.37"

# Install Genesis with AMD GPU backend
ENV GENESIS_BACKEND=gs.amdgpu
RUN pip install --no-cache-dir "genesis-world>=1.3.0"

# Install Qwen LLM dependencies for local language understanding
RUN pip install --no-cache-dir \
    "transformers>=4.57" \
    "fastapi>=0.135" \
    "uvicorn[standard]>=0.42" \
    "pydantic>=2"

# Copy project source
WORKDIR /opt/radeon-home
COPY pyproject.toml .
COPY radeon_home/ radeon_home/
COPY tests/ tests/
COPY scripts/ scripts/
COPY README.md LICENSE .

# Install RadeonHome
RUN pip install --no-cache-dir -e .

# Smoke test: verify Genesis and HIP are available
RUN python -c "\
import genesis; \
import torch; \
print(f'Genesis: {genesis.__version__}'); \
print(f'PyTorch: {torch.__version__}'); \
print(f'HIP: {torch.version.hip}'); \
assert torch.cuda.is_available(), 'ROCm GPU not detected'; \
print(f'GPU: {torch.cuda.get_device_name(0)}'); \
"

# Run the test suite
RUN python -m pytest tests/ -q

# Quick-start script
COPY bootstrap_cloud.sh .
RUN chmod +x bootstrap_cloud.sh scripts/*.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import torch; assert torch.cuda.is_available()"

ENTRYPOINT ["python", "-m", "radeon_home.cli"]
