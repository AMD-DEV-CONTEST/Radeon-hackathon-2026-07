FROM rocm/pytorch:rocm6.2_ubuntu22.04_py3.10_pytorch2.3.0

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Install vLLM with ROCm wheels
RUN pip install --no-cache-dir vllm==0.5.0 --extra-index-url https://download.pytorch.org/whl/rocm6.2

# Copy source and scripts
COPY src/ /app/src/
COPY scripts/ /app/scripts/
COPY docker-entrypoint.sh /app/

# Create data directories
RUN mkdir -p /app/data/documents \
             /app/data/vector_db \
             /app/data/memory \
             /app/data/audit

# Make scripts executable
RUN chmod +x /app/docker-entrypoint.sh /app/scripts/*.sh

EXPOSE 7860 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
