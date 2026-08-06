FROM rocm/dev-ubuntu-22.04:7.2.4

LABEL maintainer="Yang Weike"
LABEL description="CodeRisk Agent - AI-Powered Code Security Analysis on AMD GPU"

# System dependencies (deadsnakes PPA for python3.12 on Ubuntu 22.04)
RUN apt-get update && apt-get install -y software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-pip \
    python3.12-venv \
    git \
    cmake \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ROCm environment
ENV ROCM_PATH=/opt/rocm-7.2.4
ENV PATH=${ROCM_PATH}/bin:${PATH}

WORKDIR /app

# Layer 1: Dependencies (cached unless pyproject.toml changes)
COPY pyproject.toml ./
RUN pip3.12 install --no-cache-dir -e ".[dev]"

# Layer 2: Application code
COPY . .

# Non-root user (after COPY so files are owned by coderisk)
RUN useradd -m -u 1000 coderisk && chown -R coderisk:coderisk /app
USER coderisk

# Default configuration
ENV LLM_BACKEND=local_llama_cpp
ENV LOCAL_MODEL_PATH=/models/qwen2.5-coder-32b-instruct-q4_k_m.gguf
ENV LOCAL_N_GPU_LAYERS=999
ENV SEMGREP_RULES=p/default
ENV GGML_HIP=ON

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3.12 -c "from core.models import AnalysisRequest; print('OK')" || exit 1

# No ports needed — fully offline
ENTRYPOINT ["python3.12", "main.py"]
CMD ["analyze", "/workspace/src"]
