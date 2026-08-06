# RepositoryAnalysisAgent Docker Image
# Base: vllm-dev (PyTorch 2.9 + vLLM 0.16.0 + ROCm 7.2.1)
FROM 10.5.10.89:1808/xinwei/radeon-cloud/vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0

# Use the venv already in the base image
ENV PATH="/opt/venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/venv"

# ROCm stability env vars (gfx1100)
ENV PYTORCH_ROCM_ARCH=gfx1100
ENV HSA_ENABLE_SDMA=0
ENV AMD_SERIALIZE_KERNEL=3
ENV AMD_SERIALIZE_COPY=3

WORKDIR /app

# Copy requirements and install deps into the existing venv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y flash-attn flash-attn-rotary 2>/dev/null || true

# Copy application code
COPY . .

# Model path (override with -e MODEL_DIR=/your/models)
ENV MODEL_DIR=/models
ENV REPO_PATH=/workspace

# Expose ports: vLLM (8000) + RepositoryAnalysisAgent (8080)
EXPOSE 8000 8080

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
