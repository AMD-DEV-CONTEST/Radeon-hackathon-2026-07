# syntax=docker/dockerfile:1
FROM rocm/atom-dev:vllm-latest


# Build stage variables (ARG only available during build, not in runtime environment)

ARG DEBIAN_FRONTEND=noninteractive


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    # Business configuration
    AGENT_MODE=api \
    VLLM_URL=http://vllm-atom:8000 \
    # ROCm performance optimization
    HSA_OVERRIDE_GFX_VERSION=10.1.0 \
    ROCM_PATH=/opt/rocm \
    # Python async optimization
    UVLOOP_PYTHON=1 \
    # Precision assurance (ROCm/HIP)
    MIOPEN_DEBUG_AMD_WINograd=OFF \
    MIOPEN_DEBUG_CONV_DIRECT_EDGEMODE=1

WORKDIR /app

# Dependency layer: separate system dependencies from Python dependencies, maximize cache hits
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        # Async event loop optimization
        libuv1 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies: precise version locking, prioritize compiled optimized packages
COPY --chown=1000:1000 requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --no-cache-dir --upgrade pip setuptools wheel && \
    # Prioritize performance-critical packages (compiled optimization)
    pip install --no-cache-dir \
        uvloop \
        orjson \
        aiohttp[speedups] \
        -r requirements.txt

# Business code: copy last to ensure dependency layer cache stability
COPY --chown=1000:1000 . .

# Security: run as non-root
RUN useradd -m -u 1000 -s /bin/bash agent || true
USER 1000

# Health check: lightweight, consistent with business port
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost:8080/health >> /dev/null 2>&1 || exit 1

# Unified entry: run as module directly, avoid shell intermediary layer
EXPOSE 8080
ENTRYPOINT ["python", "-m", "src.main"]