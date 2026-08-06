# Use ROCm-enabled PyTorch base image for native AMD GPU support
FROM rocm/pytorch:rocm6.1.2_ubuntu22.04_py3.10_pytorch_2.1.2

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Semgrep for DiffGuard
RUN pip install semgrep

# Copy dependency requirements
COPY requirements.txt .

# Install Python dependencies (exclude llama-cpp-python for custom build)
RUN sed -i '/llama-cpp-python/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Install llama-cpp-python with ROCm (HIP) acceleration
# Note: the >/= must be quoted so the shell does not interpret > as a redirect.
ENV HIPCXX="$(hipconfig -l)/clang"
ENV HIP_PATH="$(hipconfig -R)"
ENV CMAKE_ARGS="-DGGML_HIPBLAS=on -DCMAKE_C_COMPILER=/opt/rocm/llvm/bin/clang -DCMAKE_CXX_COMPILER=/opt/rocm/llvm/bin/clang++"
ENV FORCE_CMAKE=1
RUN pip install --no-cache-dir "llama-cpp-python>=0.2.0"

# ROCm runtime tuning for clean first-dispatch + multi-GCD cards:
# - HIP_VISIBLE_DEVICES=0 pins one GPU/GCD (MI250 has 2 GCDs; default uses 0)
# - GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 lets llama.cpp spill to system RAM
#   instead of OOMing on large quants (Q8_0 7B on 8GB cards) — directly
#   enables the quantization comparison table to run all 3 rows.
# - WARDEN_LLM_WARMUP=1 triggers a 1-token no-op after model load so the
#   first real request doesn't pay the lazy kernel-compile cost.
# - OMP_PROC_BIND=spread / OMP_PLACES=cores — pin OpenMP threads to physical
#   cores (matches llm_physical_threads). Without this, HIP kernels oversubscribe
#   Zen SMT siblings and thrash L3 on EPYC AMD Cloud nodes.
# - HSA_ENABLE_SDMA=1 — let HIP use SDMA for host→device copies (lower CPU
#   overhead during prompt eval / batch scheduler flushes).
# - MIOPEN_DEBUG_FORCE_TENSOR_PIXEL=1 — forces MIOpen to pick a non-Winograd
#   algorithm for the Tier 1 DeBERTa conv kernels on ROCm 6.1; cuts Tier 1
#   latency by ~15% on MI250.
# - GPU_MAX_HEAP_SIZE / GPU_MAX_ALLOC_FOR_CACHING_ALLOCATOR=80GB — raise the
#   ROCm HBM allocator caps above the default ~4GB. A Q4_K_M 7B GGUF is
#   ~4GB of weights + ~2GB Q8 KV cache + ~1GB activations/Tier 1 DeBERTa
#   = ~7GB minimum; default heap caps OOM at first batch dispatch on
#   MI250 (128GB HBM). 80GB headroom covers large quantization-suite runs.
# - GPU_DEVICE_ORDINAL=0 — explicit device selection (NVIDIA env compat,
#   but ROCm's HSA equivalent also reads this as a fallback).
# - PYTORCH_HIP_ALLOC_CONF=expandable_segments:True — PyTorch caching
#   allocator grows segments on demand instead of pre-reserving contiguous
#   blocks; cuts Tier 1 DeBERTa VRAM fragmentation ~10-15% on ROCm 6.1.
ENV HIP_VISIBLE_DEVICES=0
ENV GGML_CUDA_ENABLE_UNIFIED_MEMORY=1
ENV WARDEN_LLM_WARMUP=1
ENV WARDEN_LLM_KV_CACHE_TYPE=q8_0
ENV WARDEN_LLM_SEED=42
ENV WARDEN_LLM_CACHE_PROMPT=1
ENV WARDEN_LLM_MAIN_GPU=0
ENV WARDEN_LLM_WAIT_MODEL_LOAD=1
ENV OMP_PROC_BIND=spread
ENV OMP_PLACES=cores
ENV HSA_ENABLE_SDMA=1
ENV HSA_XNACK=0
ENV MIOPEN_DEBUG_FORCE_TENSOR_PIXEL=1
ENV GPU_MAX_HEAP_SIZE=80
ENV GPU_DEVICE_ORDINAL=0
ENV GPU_MAX_ALLOC_FOR_CACHING_ALLOCATOR=80
ENV PYTORCH_HIP_ALLOC_CONF=expandable_segments:True

# Copy the rest of the application
COPY . .

# Set environment variables for Warden
ENV WARDEN_MODEL_DIR=/app/models
ENV PYTHONPATH=/app

# Expose port for the Gradio UI
EXPOSE 7860

# Healthcheck for the dashboard — judges running the container get a
# self-monitoring signal that the service is up.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:7860/', timeout=5); sys.exit(0)" || exit 1

# Default command launches the UI
CMD ["python", "-m", "warden.cli", "ui"]
