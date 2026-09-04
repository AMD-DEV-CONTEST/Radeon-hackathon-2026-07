# ROCm 容器镜像 —— 用于 Radeon Cloud 一键部署
# 构建: docker build -t private-rag-agent .
# 运行: docker run --device=/dev/kfd --device=/dev/dri --group-add video \
#            -p 7860:7860 private-rag-agent

FROM rocm/vllm:latest AS base
# 或使用: FROM rocm/pytorch:rocm6.x_ubuntu22.04_py3.10_pytorch_release

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip git curl ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ollama (ROCm 版)
RUN curl -fsSL https://ollama.com/install.sh | sh || true

COPY . .

EXPOSE 7860
CMD ["bash", "deploy_amd.sh"]
