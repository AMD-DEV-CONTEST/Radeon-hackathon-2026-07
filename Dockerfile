FROM rocm/pytorch:rocm6.3.3_ubuntu22.04_py3.10_pytorch_2.4.0

LABEL maintainer="ZhiYan Future Team"
LABEL description="RationalVLA: Defect-Aware Instruction Filtering for Robot Manipulation (Track 3 - AMD Radeon Hackathon 2026)"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11-utils \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir genesis-world

COPY . .

RUN mkdir -p /app/franka_fruit_pick/outputs/rationalvla/results \
    /app/franka_fruit_pick/outputs/rationalvla/stage2

ENV PYTHONPATH="/app:/app/franka_fruit_pick:${PYTHONPATH}"

RUN python3 franka_fruit_pick/setup_assets.py 2>/dev/null || echo "Assets setup note: YCB objects may need manual download"

CMD ["/bin/bash"]