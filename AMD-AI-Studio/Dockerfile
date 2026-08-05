# ============================================================
# AMD AI Studio — Docker 镜像构建文件
# 基于 ROCm 7.2 + Ubuntu 24.04，支持 AMD GPU 推理加速
# ============================================================

# ── 基础镜像（ROCm 官方） ──
# 国内用户可替换为镜像源:
#   rocm/dev-ubuntu-24.04:7.2.0
FROM rocm/dev-ubuntu-24.04:latest

LABEL maintainer="AMD AI Studio"
LABEL description="AMD AI Studio — Local AI Creation Platform"
LABEL version="1.0.0"

# ── 环境变量 ──
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV MAX_JOBS=2
ENV HF_HUB_ENABLE_HF_TRANSFER=0
ENV HF_HOME=/models/cache/huggingface
ENV MODELSCOPE_CACHE=/models/cache/modelscope
ENV TRANSFORMERS_CACHE=/models/cache/huggingface
ENV DIFFUSERS_CACHE=/models/cache/huggingface
ENV GRADIO_SERVER_NAME=0.0.0.0
ENV GRADIO_SERVER_PORT=7860

# ── 系统依赖安装 ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python 基础
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    # ROCm 运行时
    rocm-hip-libraries \
    # 工具
    git \
    git-lfs \
    curl \
    wget \
    vim \
    tmux \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    nocache \
    # 清理
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── 创建虚拟环境 ──
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── 安装 PyTorch ROCm 版 ──
RUN pip install --upgrade pip && \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm7.2

# ── 复制项目代码 ──
WORKDIR /workspace
COPY . /workspace/amd-ai-studio
WORKDIR /workspace/amd-ai-studio

# ── 安装项目依赖 ──
RUN pip install -r requirements.txt

# ── 创建输出目录 ──
RUN mkdir -p outputs/images outputs/videos outputs/gifs outputs/finetune

# ── 默认启动命令 ──
EXPOSE 7860
CMD ["python", "app.py"]